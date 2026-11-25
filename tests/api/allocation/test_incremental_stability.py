"""Two properties reviewers feel directly, asserted end-to-end against the durable rows.

2. **Re-running an unchanged campaign changes nothing.** Same cases, same reviewers, same policy =>
   zero new, zero moved, and not one assignment row touched. Every move costs a reviewer their
   place, so movement must be caused by an actual change in the campaign, never by re-running the
   allocation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select

from review_platform.db.session import Database
from review_platform.review.models import (
    Assignment,
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity, ReviewIdentity

CASE_IDS = [f"STAB-{index:03d}" for index in range(6)]
# Three fields per case across three review kinds: the shape that makes "did the whole case move?"
# a meaningful question at all.
CASE_FIELDS: list[tuple[str, str]] = [
    ("metadata_field", "Citation Neutral"),
    ("cited_case", "Cited case"),
    ("statute_reference", "Statute cited"),
]
REVIEWS_PER_CASE = 2


def _insert_campaign(
    database: Database,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    key: str,
    reviewer_ids: list[uuid.UUID],
) -> uuid.UUID:
    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=tenant_id,
            key=key,
            name="Incremental stability test",
            status="draft",
            subject_kind="case",
            review_kind="metadata_field",
            policy_json={"selected_reviewer_ids": [str(r) for r in reviewer_ids]},
            review_scope_json={"group_ids": [], "review_kinds": [], "source_families": []},
            manifest_digest="incremental-stability-manifest",
            created_by=created_by,
        )
        session.add(campaign)
        session.flush()
        for case_id in CASE_IDS:
            snapshot = SourceSnapshot(
                tenant_id=tenant_id,
                contract_version="test-fixture/v1",
                source_version="test-fixture",
                external_item_key=f"test:{key}:{case_id}",
                input_digest="incremental-stability-digest",
            )
            session.add(snapshot)
            session.flush()
            if campaign.source_snapshot_id is None:
                campaign.source_snapshot_id = snapshot.id
            subject = ReviewSubject(
                tenant_id=tenant_id,
                source_snapshot_id=snapshot.id,
                subject_kind="case",
                external_subject_id=f"subject_{case_id}",
                display_title=f"Case {case_id}",
                display_subtitle="Case metadata",
                primary_source_ref=f"source_{case_id}",
                attributes_json={"snapshot_local_case_external_id": case_id},
            )
            session.add(subject)
            session.flush()
            for review_kind, label in CASE_FIELDS:
                unit = ReviewUnit(
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    review_subject_id=subject.id,
                    review_kind=review_kind,
                    question=f"Confirm {label}",
                    safe_field_label=label,
                    input_digest="incremental-stability-digest",
                )
                session.add(unit)
                session.flush()
                value = f"{label} {case_id}"
                session.add(
                    Candidate(
                        tenant_id=tenant_id,
                        review_unit_id=unit.id,
                        label="A",
                        source_kind="deterministic",
                        verdict="supported",
                        value_json=value,
                        rationale="test fixture",
                    )
                )
                session.add(
                    EvidenceWindow(
                        tenant_id=tenant_id,
                        review_unit_id=unit.id,
                        ordinal=0,
                        kind="quote",
                        snippet=value,
                        source_sha256="0" * 64,
                    )
                )
        return campaign.id


def _initial_policy(reviewers: list[ReviewIdentity]) -> dict[str, object]:
    return {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "reviewer_ids": [str(r.user_id) for r in reviewers],
        "target_distinct_subjects": len(CASE_IDS),
        "target_per_reviewer_workload": len(CASE_IDS),
        "target_pairwise_overlap": 0,
        "target_global_overlap": 0,
        "uniform_reviews_per_subject": REVIEWS_PER_CASE,
        "rolling_window_size": 0,
        "rolling_window_stride": 1,
        "hub_priority_count": 0,
        "random_seed": "stability-seed",
        "allocation_policy_version": "reviewer-allocation/v1",
        "metric_weights": {},
    }


def _incremental_body(reviewers: list[ReviewIdentity], base_run_id: str) -> dict[str, object]:
    return {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "reviewer_ids": [str(r.user_id) for r in reviewers],
        "min_reviews_per_subject": REVIEWS_PER_CASE,
        "movement_policy": {
            "allow_rebalance_unclaimed": True,
            "allow_rebalance_claimed": True,
            "allow_rebalance_draft": False,
        },
        "random_seed": "stability-incr-seed",
        "allocation_policy_version": "reviewer-allocation/v1",
        "base_run_id": base_run_id,
    }


def _assignment_rows(database: Database, tenant_id: uuid.UUID) -> dict[uuid.UUID, tuple[str, str]]:
    """Every assignment row as ``id -> (reviewer, status)`` -- the state a reviewer experiences."""

    with database.session() as session:
        rows = session.execute(
            select(Assignment.id, Assignment.reviewer_id, Assignment.status).where(
                Assignment.tenant_id == tenant_id
            )
        ).all()
    return {row[0]: (str(row[1]), row[2]) for row in rows}


def _units_held_per_case(
    database: Database, tenant_id: uuid.UUID
) -> tuple[dict[tuple[str, str], set[uuid.UUID]], dict[str, set[uuid.UUID]]]:
    """Live units each reviewer holds per case, and every in-scope unit of each case."""

    held: dict[tuple[str, str], set[uuid.UUID]] = defaultdict(set)
    case_units: dict[str, set[uuid.UUID]] = defaultdict(set)
    with database.session() as session:
        units = session.execute(
            select(ReviewUnit.id, ReviewSubject.attributes_json)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(ReviewUnit.tenant_id == tenant_id)
        ).all()
        for unit_id, attributes in units:
            case_units[attributes["snapshot_local_case_external_id"]].add(unit_id)
        rows = session.execute(
            select(Assignment.reviewer_id, Assignment.status, Assignment.review_unit_id)
            .select_from(Assignment)
            .where(Assignment.tenant_id == tenant_id)
        ).all()
        unit_case = {
            unit_id: attributes["snapshot_local_case_external_id"] for unit_id, attributes in units
        }
    for reviewer_id, status, unit_id in rows:
        if status == "released":
            continue
        held[(unit_case[unit_id], str(reviewer_id))].add(unit_id)
    return held, case_units


async def _publish_initial(client, headers, runs: str, reviewers: list[ReviewIdentity]) -> str:
    persisted = await client.post(
        runs,
        json=_initial_policy(reviewers),
        headers={**headers, "Idempotency-Key": "stability-persist-1"},
    )
    assert persisted.status_code == 201, persisted.text
    run_id = str(persisted.json()["run_id"])
    published = await client.post(
        f"{runs}/{run_id}/publish", headers={**headers, "Idempotency-Key": "stability-publish-1"}
    )
    assert published.status_code == 201, published.text
    return run_id


@pytest.mark.anyio
async def test_adding_a_reviewer_moves_whole_cases_and_never_fragments_one(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="stab-manager@example.test", role="campaign_manager"
    )
    r1, r2, r3 = [
        add_review_user(database, settings, admin, email=f"stab-r{i}@example.test", role="reviewer")
        for i in range(1, 4)
    ]
    campaign_id = _insert_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="incremental-stability-fragments",
        reviewer_ids=[r1.user_id, r2.user_id],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"
        base_run_id = await _publish_initial(manager_client, headers, runs, [r1, r2])

        body = _incremental_body([r1, r2, r3], base_run_id)
        persisted = await manager_client.post(
            f"{runs}/incremental", json=body, headers={**headers, "Idempotency-Key": "stab-incr-1"}
        )
        assert persisted.status_code == 201, persisted.text
        published = await manager_client.post(
            f"{runs}/{str(persisted.json()['run_id'])}/publish-incremental",
            headers={**headers, "Idempotency-Key": "stab-incr-publish-1"},
        )
        assert published.status_code == 201, published.text

        held, case_units = _units_held_per_case(database, admin.tenant_id)
        # Whoever holds a case holds all three of its fields -- no partial case anywhere.
        for (case_id, reviewer_id), units in held.items():
            assert units == case_units[case_id], (case_id, reviewer_id, len(units))
        # And coverage is still exactly two reviewers per case, on every case.
        reviewers_per_case: dict[str, int] = defaultdict(int)
        for case_id, _reviewer_id in held:
            reviewers_per_case[case_id] += 1
        assert set(reviewers_per_case) == set(CASE_IDS)
        assert all(count == REVIEWS_PER_CASE for count in reviewers_per_case.values()), (
            reviewers_per_case
        )


@pytest.mark.anyio
async def test_rerunning_an_unchanged_campaign_moves_nothing(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """No new cases and no new reviewers must mean no churn: the reviewers keep exactly the work
    they had, and no ``released`` tombstone is created for anyone."""

    manager = add_review_user(
        database, settings, admin, email="stab-noop-manager@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"stab-noop-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    campaign_id = _insert_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="incremental-stability-noop",
        reviewer_ids=[r1.user_id, r2.user_id],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"
        base_run_id = await _publish_initial(manager_client, headers, runs, [r1, r2])
        before = _assignment_rows(database, admin.tenant_id)
        assert before

        body = _incremental_body([r1, r2], base_run_id)
        preview = await manager_client.post(
            f"{runs}/incremental-preview", json=body, headers=headers
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["new_assignment_count"] == 0, preview.text
        assert preview.json()["moved_assignment_count"] == 0, preview.text

        persisted = await manager_client.post(
            f"{runs}/incremental", json=body, headers={**headers, "Idempotency-Key": "stab-noop-1"}
        )
        assert persisted.status_code == 201, persisted.text
        published = await manager_client.post(
            f"{runs}/{str(persisted.json()['run_id'])}/publish-incremental",
            headers={**headers, "Idempotency-Key": "stab-noop-publish-1"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["new_assignment_count"] == 0, published.text
        assert published.json()["moved_assignment_count"] == 0, published.text

        # The rows themselves are the assertion that matters: same ids, same owners, same statuses.
        assert _assignment_rows(database, admin.tenant_id) == before


def _append_case(
    database: Database, tenant_id: uuid.UUID, campaign_id: uuid.UUID, *, case_id: str
) -> None:
    """Add one more fully-formed case to a published campaign, as a later import would."""

    with database.session() as session, session.begin():
        snapshot = SourceSnapshot(
            tenant_id=tenant_id,
            contract_version="test-fixture/v1",
            source_version="test-fixture",
            external_item_key=f"test:appended:{case_id}",
            input_digest="incremental-stability-digest",
        )
        session.add(snapshot)
        session.flush()
        subject = ReviewSubject(
            tenant_id=tenant_id,
            source_snapshot_id=snapshot.id,
            subject_kind="case",
            external_subject_id=f"subject_{case_id}",
            display_title=f"Case {case_id}",
            display_subtitle="Case metadata",
            primary_source_ref=f"source_{case_id}",
            attributes_json={"snapshot_local_case_external_id": case_id},
        )
        session.add(subject)
        session.flush()
        for review_kind, label in CASE_FIELDS:
            unit = ReviewUnit(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                review_subject_id=subject.id,
                review_kind=review_kind,
                question=f"Confirm {label}",
                safe_field_label=label,
                input_digest="incremental-stability-digest",
            )
            session.add(unit)
            session.flush()
            session.add(
                Candidate(
                    tenant_id=tenant_id,
                    review_unit_id=unit.id,
                    label="A",
                    source_kind="deterministic",
                    verdict="supported",
                    value_json=f"{label} {case_id}",
                    rationale="test fixture",
                )
            )
            session.add(
                EvidenceWindow(
                    tenant_id=tenant_id,
                    review_unit_id=unit.id,
                    ordinal=0,
                    kind="quote",
                    snippet=f"{label} {case_id}",
                    source_sha256="0" * 64,
                )
            )


@pytest.mark.anyio
async def test_appending_a_case_assigns_only_that_case(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Adding cases is the other legitimate reason to re-run. It must cover the new case and leave
    every reviewer's existing work exactly where it is."""

    manager = add_review_user(
        database, settings, admin, email="stab-add-manager@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"stab-add-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    campaign_id = _insert_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="incremental-stability-append",
        reviewer_ids=[r1.user_id, r2.user_id],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"
        base_run_id = await _publish_initial(manager_client, headers, runs, [r1, r2])
        before = _assignment_rows(database, admin.tenant_id)

        _append_case(database, admin.tenant_id, campaign_id, case_id="STAB-APPENDED")

        body = _incremental_body([r1, r2], base_run_id)
        persisted = await manager_client.post(
            f"{runs}/incremental", json=body, headers={**headers, "Idempotency-Key": "stab-add-1"}
        )
        assert persisted.status_code == 201, persisted.text
        published = await manager_client.post(
            f"{runs}/{str(persisted.json()['run_id'])}/publish-incremental",
            headers={**headers, "Idempotency-Key": "stab-add-publish-1"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["moved_assignment_count"] == 0, published.text

        after = _assignment_rows(database, admin.tenant_id)
        # Nothing that existed changed hands or status; the only new rows are the appended case's.
        assert {row_id: after[row_id] for row_id in before} == before
        held, case_units = _units_held_per_case(database, admin.tenant_id)
        appended_holders = {
            reviewer_id for (case_id, reviewer_id) in held if case_id == "STAB-APPENDED"
        }
        assert len(appended_holders) == REVIEWS_PER_CASE
        for (case_id, _reviewer), units in held.items():
            assert units == case_units[case_id], case_id
