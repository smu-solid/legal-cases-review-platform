"""Adding a reviewer to a published campaign must rebalance, not over-assign.

End-to-end companion to ``test_adding_a_reviewer_does_not_push_subjects_past_the_review_target``
(``tests/unit/allocation/test_incremental_planner.py``), which exercises the pure planner only.
This drives the real admin API and asserts against the durable ``Assignment`` rows, so it also
covers the input-assembly half of the defect: ``_classify_existing_assignments`` used to re-derive
its own ``review_kind`` filter, hiding the campaign's real coverage from the planner, which then
provisioned fresh reviewers on top of assignments it kept. Live symptom before the fix was
"68 new, 0 moved" with 68 of 102 units sitting on three reviewers in a two-reviews-per-case
campaign.

It also guards the property that makes an agreement study meaningful: the reviewer *pairs* sharing
a case stay spread across the pool instead of one pair carrying everything.
"""

from __future__ import annotations

import uuid
from collections import Counter
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

CASE_COUNT = 6
REVIEWS_PER_CASE = 2


def _insert_campaign(
    database: Database,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    key: str,
    reviewer_ids: list[uuid.UUID],
) -> uuid.UUID:
    """A draft campaign of ``CASE_COUNT`` single-field cases, built at INSERT time.

    One metadata field per case keeps case-level and unit-level counts equal here, so a coverage
    assertion reads unambiguously as "this case has exactly N reviewers"; the case/unit fan-out is
    covered separately in ``test_case_native_allocation``.
    """

    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=tenant_id,
            key=key,
            name="Reviewer addition coverage test",
            status="draft",
            subject_kind="case",
            review_kind="metadata_field",
            policy_json={"selected_reviewer_ids": [str(r) for r in reviewer_ids]},
            review_scope_json={"group_ids": [], "review_kinds": [], "source_families": []},
            manifest_digest="reviewer-addition-manifest",
            created_by=created_by,
        )
        session.add(campaign)
        session.flush()
        for index in range(CASE_COUNT):
            case_id = f"ADD-REV-{index:03d}"
            snapshot = SourceSnapshot(
                tenant_id=tenant_id,
                contract_version="test-fixture/v1",
                source_version="test-fixture",
                external_item_key=f"test:{key}:{case_id}",
                input_digest="reviewer-addition-digest",
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
            unit = ReviewUnit(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                review_subject_id=subject.id,
                review_kind="metadata_field",
                question="Confirm Citation Neutral",
                safe_field_label="Citation Neutral",
                input_digest="reviewer-addition-digest",
            )
            session.add(unit)
            session.flush()
            value = f"[2024] SGCA {index}"
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


def _policy(reviewers: list[ReviewIdentity], seed: str) -> dict[str, object]:
    return {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "reviewer_ids": [str(r.user_id) for r in reviewers],
        "target_distinct_subjects": CASE_COUNT,
        "target_per_reviewer_workload": CASE_COUNT,
        "target_pairwise_overlap": 0,
        "target_global_overlap": 0,
        "uniform_reviews_per_subject": REVIEWS_PER_CASE,
        "rolling_window_size": 0,
        "rolling_window_stride": 1,
        "hub_priority_count": 0,
        "random_seed": seed,
        "allocation_policy_version": "reviewer-allocation/v1",
        "metric_weights": {},
    }


def _append_single_field_case(
    database: Database,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    case_id: str,
) -> None:
    """Append one case after publication, matching the campaign top-up shape."""
    with database.session() as session, session.begin():
        snapshot = SourceSnapshot(
            tenant_id=tenant_id,
            contract_version="test-fixture/v1",
            source_version="test-fixture",
            external_item_key=f"test:readded-reviewer:{case_id}",
            input_digest="reviewer-readdition-digest",
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
        unit = ReviewUnit(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            review_subject_id=subject.id,
            review_kind="metadata_field",
            question="Confirm Citation Neutral",
            safe_field_label="Citation Neutral",
            input_digest="reviewer-readdition-digest",
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
                value_json="[2024] SGCA 99",
                rationale="test fixture",
            )
        )
        session.add(
            EvidenceWindow(
                tenant_id=tenant_id,
                review_unit_id=unit.id,
                ordinal=0,
                kind="quote",
                snippet="[2024] SGCA 99",
                source_sha256="1" * 64,
            )
        )


def _live_coverage(database: Database, tenant_id: uuid.UUID) -> dict[str, set[uuid.UUID]]:
    """Map each case to the reviewers holding a live (non-released) assignment for it."""

    coverage: dict[str, set[uuid.UUID]] = {}
    with database.session() as session:
        rows = session.execute(
            select(Assignment.reviewer_id, Assignment.status, ReviewSubject)
            .select_from(Assignment)
            .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(Assignment.tenant_id == tenant_id)
        ).all()
    for reviewer_id, status, subject in rows:
        if status == "released":
            continue
        case_id = subject.attributes_json["snapshot_local_case_external_id"]
        coverage.setdefault(case_id, set()).add(reviewer_id)
    return coverage


@pytest.mark.anyio
async def test_adding_a_reviewer_rebalances_and_holds_exact_coverage(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="addrev-manager@example.test", role="campaign_manager"
    )
    r1, r2, r3 = [
        add_review_user(
            database, settings, admin, email=f"addrev-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 4)
    ]
    campaign_id = _insert_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="reviewer-addition-coverage",
        reviewer_ids=[r1.user_id, r2.user_id],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"

        # --- initial publish with two reviewers ---
        persisted = await manager_client.post(
            runs,
            json=_policy([r1, r2], "addrev-seed"),
            headers={**headers, "Idempotency-Key": "addrev-persist-1"},
        )
        assert persisted.status_code == 201, persisted.text
        base_run_id = str(persisted.json()["run_id"])
        published = await manager_client.post(
            f"{runs}/{base_run_id}/publish",
            headers={**headers, "Idempotency-Key": "addrev-publish-1"},
        )
        assert published.status_code == 201, published.text

        before = _live_coverage(database, admin.tenant_id)
        assert len(before) == CASE_COUNT
        assert all(len(ids) == REVIEWS_PER_CASE for ids in before.values()), before

        # --- add a third reviewer, keeping reviews-per-case at two ---
        incremental_body = {
            "subject_kind": "case",
            "review_kind": "metadata_field",
            "reviewer_ids": [str(r1.user_id), str(r2.user_id), str(r3.user_id)],
            "min_reviews_per_subject": REVIEWS_PER_CASE,
            "movement_policy": {
                "allow_rebalance_unclaimed": True,
                "allow_rebalance_claimed": True,
                "allow_rebalance_draft": False,
            },
            "random_seed": "addrev-incr-seed",
            "allocation_policy_version": "reviewer-allocation/v1",
            "base_run_id": base_run_id,
        }
        preview = await manager_client.post(
            f"{runs}/incremental-preview", json=incremental_body, headers=headers
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["feasibility"]["status"] in {"feasible", "feasible_with_warnings"}
        # The defect's signature was a large "new" count with nothing moved: the planner could not
        # see the coverage that already existed, so it provisioned on top of it. Rebalancing a
        # fully covered campaign onto an extra reviewer is movement, not new work.
        assert preview_body["new_assignment_count"] == 0, preview_body
        assert preview_body["moved_assignment_count"] > 0, preview_body
        # Both granularities are reported for the update, exactly as for an initial run. One field
        # per case here, so the two are equal -- but both must be present and self-consistent.
        assert preview_body["moved_assignment_counts"] == {
            "cases": preview_body["moved_assignment_count"],
            "review_units": preview_body["moved_assignment_count"],
        }

        persisted_incr = await manager_client.post(
            f"{runs}/incremental",
            json=incremental_body,
            headers={**headers, "Idempotency-Key": "addrev-incr-persist-1"},
        )
        assert persisted_incr.status_code == 201, persisted_incr.text
        incr_run_id = str(persisted_incr.json()["run_id"])
        published_incr = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "addrev-incr-publish-1"},
        )
        assert published_incr.status_code == 201, published_incr.text
        publish_body = published_incr.json()
        assert (
            publish_body["new_assignment_counts"]["cases"] == publish_body["new_assignment_count"]
        )
        assert (
            publish_body["moved_assignment_counts"]["cases"]
            == publish_body["moved_assignment_count"]
        )

        # --- remove r3 and publish: every row they held becomes a released audit tombstone ---
        removal_body = {
            **incremental_body,
            "reviewer_ids": [str(r1.user_id), str(r2.user_id)],
            "base_run_id": incr_run_id,
            "random_seed": "remove-r3-seed",
        }
        removed_run = await manager_client.post(
            f"{runs}/incremental",
            json=removal_body,
            headers={**headers, "Idempotency-Key": "remove-r3-persist"},
        )
        assert removed_run.status_code == 201, removed_run.text
        removed_run_id = str(removed_run.json()["run_id"])
        removed_publish = await manager_client.post(
            f"{runs}/{removed_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "remove-r3-publish"},
        )
        assert removed_publish.status_code == 201, removed_publish.text
        assert all(
            r3.user_id not in ids for ids in _live_coverage(database, admin.tenant_id).values()
        )

        # --- top up one case, add r3 back, and publish again ---
        _append_single_field_case(
            database,
            admin.tenant_id,
            campaign_id,
            case_id="ADD-REV-TOPUP",
        )
        readd_body = {
            **incremental_body,
            "base_run_id": removed_run_id,
            "random_seed": "readd-r3-seed",
        }
        readd_preview = await manager_client.post(
            f"{runs}/incremental-preview", json=readd_body, headers=headers
        )
        assert readd_preview.status_code == 200, readd_preview.text
        assert readd_preview.json()["unassigned_subject_count"] == 0
        readd_run = await manager_client.post(
            f"{runs}/incremental",
            json=readd_body,
            headers={**headers, "Idempotency-Key": "readd-r3-persist"},
        )
        assert readd_run.status_code == 201, readd_run.text
        readd_run_id = str(readd_run.json()["run_id"])
        readd_publish = await manager_client.post(
            f"{runs}/{readd_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "readd-r3-publish"},
        )
        assert readd_publish.status_code == 201, readd_publish.text

    # --- the durable state, which is what actually matters ---
    after = _live_coverage(database, admin.tenant_id)
    assert len(after) == CASE_COUNT + 1
    # Every case still reviewed by EXACTLY the configured number of distinct reviewers -- not one
    # more because a reviewer joined.
    for case_id, reviewer_ids in sorted(after.items()):
        assert len(reviewer_ids) == REVIEWS_PER_CASE, (
            f"{case_id} ended on {len(reviewer_ids)} reviewers, expected {REVIEWS_PER_CASE}"
        )
    # The new reviewer actually received work, and the load is even within one case.
    workloads = Counter()
    for reviewer_ids in after.values():
        for reviewer_id in reviewer_ids:
            workloads[reviewer_id] += 1
    assert r3.user_id in workloads, "the added reviewer received nothing"
    assert max(workloads.values()) - min(workloads.values()) <= 1, dict(workloads)
    # No case is reviewed twice by the same person, and the pairing is not concentrated on one
    # pair of reviewers now that three are available.
    pairs = Counter(tuple(sorted(map(str, ids))) for ids in after.values())
    assert len(pairs) > 1, dict(pairs)
