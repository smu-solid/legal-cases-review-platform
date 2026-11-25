"""Case-native allocation: a reviewer assigned a case is assigned *every* in-scope field of that
case, spanning all review kinds (metadata_field, cited_case, statute_reference)."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import func, select

from review_platform.db.session import Database
from review_platform.review.models import (
    Assignment,
    AssignmentPlan,
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

# Two cases, each with the same three in-scope fields drawn from three different review kinds. The
# per-case field set is what a real case looks like: metadata, a cited case, and a statute.
CASE_FIELDS: list[tuple[str, str, str]] = [
    ("metadata_field", "Citation Neutral", "[2024] SGCA {n}"),
    ("cited_case", "Cited case", "[2019] SGHC {n}"),
    ("statute_reference", "Statute cited", "Penal Code s {n}"),
]
CASE_IDS = ["CASE-NATIVE-001", "CASE-NATIVE-002"]


def _insert_scoped_multi_field_campaign(
    database: Database,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    key: str,
    reviewer_ids: list[uuid.UUID],
) -> uuid.UUID:
    """A draft, scope-declared campaign whose cases each carry three fields across three review
    kinds, baked in at INSERT time so the publish-immutability trigger is never tripped.

    An empty ``group_ids``/``review_kinds`` scope means "every field of every selected case is in
    scope" -- the case-native pool must therefore span all three review kinds, not just metadata.
    """

    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=tenant_id,
            key=key,
            name="Case-native allocation test",
            status="draft",
            subject_kind="case",
            review_kind="metadata_field",
            policy_json={"selected_reviewer_ids": [str(r) for r in reviewer_ids]},
            review_scope_json={"group_ids": [], "review_kinds": [], "source_families": []},
            manifest_digest="case-native-manifest",
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
                input_digest="case-native-digest",
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
            for review_kind, label, value_template in CASE_FIELDS:
                unit = ReviewUnit(
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    review_subject_id=subject.id,
                    review_kind=review_kind,
                    question=f"Confirm {label}",
                    safe_field_label=label,
                    input_digest="case-native-digest",
                )
                session.add(unit)
                session.flush()
                value = value_template.format(n=case_id[-1])
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


def _policy(reviewers: list[ReviewIdentity]) -> dict[str, object]:
    return {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "reviewer_ids": [str(r.user_id) for r in reviewers],
        # Denominated in CASES: two distinct cases, each reviewed by both reviewers.
        "target_distinct_subjects": 2,
        "target_per_reviewer_workload": 2,
        "target_pairwise_overlap": 0,
        "target_global_overlap": 0,
        "uniform_reviews_per_subject": 2,
        "rolling_window_size": 2,
        "rolling_window_stride": 1,
        "hub_priority_count": 0,
        "random_seed": "case-native-seed",
        "allocation_policy_version": "reviewer-allocation/v1",
        "metric_weights": {},
    }


@pytest.mark.anyio
async def test_case_native_allocation_fans_out_every_field_of_a_case(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="cn-manager@example.test", role="campaign_manager"
    )
    reviewers = [
        add_review_user(
            database, settings, admin, email=f"cn-reviewer-{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    campaign_id = _insert_scoped_multi_field_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="case-native",
        reviewer_ids=[r.user_id for r in reviewers],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"

        preview = await manager_client.post(
            f"{runs}/preview", json=_policy(reviewers), headers=headers
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["feasibility"]["status"] == "feasible"

        persisted = await manager_client.post(
            runs, json=_policy(reviewers), headers={**headers, "Idempotency-Key": "cn-persist-1"}
        )
        assert persisted.status_code == 201, persisted.text
        # Planner counts CASES, not fields: two cases x two reviewers = four case-level assignments.
        assert persisted.json()["planned_assignment_count"] == 4
        run_id = persisted.json()["run_id"]

        publish = await manager_client.post(
            f"{runs}/{run_id}/publish", headers={**headers, "Idempotency-Key": "cn-publish-1"}
        )
        assert publish.status_code == 201, publish.text
        # Fan-out at publish: four case-level assignments x three fields each = twelve unit rows.
        assert publish.json()["created_assignment_count"] == 12

    # Fan-out: each of the four case-level assignments becomes three per-unit rows -> 12.
    with database.session() as session:
        plan_count = session.scalar(
            select(func.count())
            .select_from(AssignmentPlan)
            .where(AssignmentPlan.tenant_id == admin.tenant_id)
        )
        assignment_rows = list(
            session.scalars(select(Assignment).where(Assignment.tenant_id == admin.tenant_id))
        )
        plan_rows = list(
            session.scalars(
                select(AssignmentPlan).where(AssignmentPlan.tenant_id == admin.tenant_id)
            )
        )
    assert plan_count == 12
    assert len(assignment_rows) == 12

    # Plan/assignment parity. Admin allocation monitoring reads AssignmentPlan while the reviewer
    # surfaces read Assignment, so the two must describe the same (review_unit, reviewer) set and be
    # linked 1:1. A divergence here is invisible to reviewers but silently corrupts admin counts.
    assert all(plan.status == "published" for plan in plan_rows)
    assert {plan.assignment_id for plan in plan_rows} == {row.id for row in assignment_rows}
    assert {(plan.review_unit_id, plan.reviewer_id) for plan in plan_rows} == {
        (row.review_unit_id, row.reviewer_id) for row in assignment_rows
    }

    # Every reviewer owns all three fields of every case they were assigned (no scattering).
    per_reviewer_units_by_case: dict[uuid.UUID, dict[str, int]] = {}
    with database.session() as session:
        for row in assignment_rows:
            unit = session.get(ReviewUnit, row.review_unit_id)
            assert unit is not None
            subject = session.get(ReviewSubject, unit.review_subject_id)
            assert subject is not None
            case_id = subject.attributes_json["snapshot_local_case_external_id"]
            per_reviewer_units_by_case.setdefault(row.reviewer_id, {}).setdefault(case_id, 0)
            per_reviewer_units_by_case[row.reviewer_id][case_id] += 1
    for _reviewer_id, by_case in per_reviewer_units_by_case.items():
        assert set(by_case) == set(CASE_IDS)
        assert all(count == len(CASE_FIELDS) for count in by_case.values())

    # The reviewer's grouped workspace now shows all three fields of one case, not one.
    first = reviewers[0]
    an_assignment = next(a for a in assignment_rows if a.reviewer_id == first.user_id)
    async with AsyncExitStack() as stack:
        (reviewer_client,) = await open_clients(stack, settings, 1)
        await authenticate(reviewer_client, first)
        bundle = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{an_assignment.id}/grouped-bundle"
        )
        assert bundle.status_code == 200, bundle.text
        items = [item for group in bundle.json()["field_groups"] for item in group["items"]]
    assert len(items) == len(CASE_FIELDS)


@pytest.mark.anyio
async def test_preview_and_publish_report_the_same_two_granularities(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Preview and publish must quote the same case-level AND review-unit-level counts.

    Regression guard for the admin screen reporting one campaign as two different sizes. The
    pre-publish panel quoted ``cases x reviews_per_case`` while the publish result quoted the
    fanned-out ``AssignmentPlan`` row count, both labelled only "assignments" -- so a campaign that
    was 8 in one place was 40 in another. Each surface now carries both numbers, and preview must
    predict exactly what publish creates or the panel is lying about the size of the run.

    This fixture is the same shape in miniature: 2 cases x 2 reviewers = 4 case assignments, each
    fanning out over 3 in-scope fields = 12 review-unit assignments.
    """

    manager = add_review_user(
        database, settings, admin, email="cn-gran-manager@example.test", role="campaign_manager"
    )
    reviewers = [
        add_review_user(
            database, settings, admin, email=f"cn-gran-reviewer-{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    campaign_id = _insert_scoped_multi_field_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="case-native-granularity",
        reviewer_ids=[r.user_id for r in reviewers],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"
        summary_url = (
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}"
            "/allocation-summary"
        )

        preview = await manager_client.post(
            f"{runs}/preview", json=_policy(reviewers), headers=headers
        )
        assert preview.status_code == 200, preview.text
        planned = preview.json()["planned_assignment_counts"]
        assert planned == {"cases": 4, "review_units": 12}

        persisted = await manager_client.post(
            runs,
            json=_policy(reviewers),
            headers={**headers, "Idempotency-Key": "cn-gran-persist-1"},
        )
        assert persisted.status_code == 201, persisted.text
        run_id = persisted.json()["run_id"]

        publish = await manager_client.post(
            f"{runs}/{run_id}/publish",
            headers={**headers, "Idempotency-Key": "cn-gran-publish-1"},
        )
        assert publish.status_code == 201, publish.text
        published = publish.json()

        # The preview's promise is exactly what publishing delivered, at BOTH granularities.
        assert published["published_assignment_counts"] == planned
        # ...and the pre-existing unit-level scalar still agrees with the unit-level half, so the
        # richer shape did not quietly redefine the number older clients read.
        assert published["published_assignment_count"] == planned["review_units"]

        # The pre-publish panel now sources both numbers too, so it can no longer disagree with the
        # publish result it precedes.
        summary = await manager_client.get(summary_url)
        assert summary.status_code == 200, summary.text
        body = summary.json()
    assert body["selected_cases"] == len(CASE_IDS)
    assert body["review_units"] == len(CASE_IDS) * len(CASE_FIELDS)
    assert body["total_assignments"] == planned["cases"]
    assert body["total_unit_assignments"] == planned["review_units"]


@pytest.mark.anyio
async def test_incremental_rebalance_moves_whole_cases_not_loose_fields(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Adding a reviewer must not shatter a case across more reviewers than it has reviews.

    Regression for a defect found by a local click-through. The initial path allocates whole cases
    and fans out; the incremental path planned per *review unit*, so a rebalance moved individual
    fields. Every unit still ended with the right number of reviewers, but no reviewer held the
    whole case any more: live, one 18-unit case ended split 8/15/13 across three reviewers in a
    two-reviews-per-case campaign, and reviewers saw partial cases in their grouped workspace --
    exactly what case-native allocation exists to prevent.

    The incremental subject is now the case, like the initial path, so a moved case moves with all
    of its in-scope units.
    """

    manager = add_review_user(
        database, settings, admin, email="cn-incr-manager@example.test", role="campaign_manager"
    )
    r1, r2, r3 = [
        add_review_user(
            database, settings, admin, email=f"cn-incr-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 4)
    ]
    campaign_id = _insert_scoped_multi_field_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="case-native-incremental",
        reviewer_ids=[r1.user_id, r2.user_id],
    )

    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/allocation-runs"

        persisted = await manager_client.post(
            runs, json=_policy([r1, r2]), headers={**headers, "Idempotency-Key": "cn-incr-p1"}
        )
        assert persisted.status_code == 201, persisted.text
        base_run_id = str(persisted.json()["run_id"])
        published = await manager_client.post(
            f"{runs}/{base_run_id}/publish",
            headers={**headers, "Idempotency-Key": "cn-incr-pub1"},
        )
        assert published.status_code == 201, published.text

        incremental_body = {
            "subject_kind": "case",
            "review_kind": "metadata_field",
            "reviewer_ids": [str(r1.user_id), str(r2.user_id), str(r3.user_id)],
            "min_reviews_per_subject": 2,
            "movement_policy": {
                "allow_rebalance_unclaimed": True,
                "allow_rebalance_claimed": True,
                "allow_rebalance_draft": False,
            },
            "random_seed": "cn-incr-seed",
            "allocation_policy_version": "reviewer-allocation/v1",
            "base_run_id": base_run_id,
        }
        preview = await manager_client.post(
            f"{runs}/incremental-preview", json=incremental_body, headers=headers
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        # Subjects are cases now, not the 6 review units.
        assert preview_body["subject_count"] == len(CASE_IDS)
        # A moved case is one case assignment but three review-unit assignments.
        moved = preview_body["moved_assignment_counts"]
        assert moved["review_units"] == moved["cases"] * len(CASE_FIELDS), preview_body

        persisted_incr = await manager_client.post(
            f"{runs}/incremental",
            json=incremental_body,
            headers={**headers, "Idempotency-Key": "cn-incr-p2"},
        )
        assert persisted_incr.status_code == 201, persisted_incr.text
        incr_run_id = str(persisted_incr.json()["run_id"])
        published_incr = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "cn-incr-pub2"},
        )
        assert published_incr.status_code == 201, published_incr.text

    # The durable state: no case may be held in fragments.
    held: dict[str, dict[uuid.UUID, int]] = {}
    with database.session() as session:
        rows = list(
            session.scalars(select(Assignment).where(Assignment.tenant_id == admin.tenant_id))
        )
        for row in rows:
            if row.status == "released":
                continue
            unit = session.get(ReviewUnit, row.review_unit_id)
            assert unit is not None
            subject = session.get(ReviewSubject, unit.review_subject_id)
            assert subject is not None
            case_id = subject.attributes_json["snapshot_local_case_external_id"]
            held.setdefault(case_id, {}).setdefault(row.reviewer_id, 0)
            held[case_id][row.reviewer_id] += 1

    assert set(held) == set(CASE_IDS)
    for case_id, by_reviewer in sorted(held.items()):
        # Exactly the configured number of reviewers on the case...
        assert len(by_reviewer) == 2, f"{case_id} is held by {len(by_reviewer)} reviewers"
        # ...and each of them holds ALL of its fields, never a fragment.
        assert all(count == len(CASE_FIELDS) for count in by_reviewer.values()), (
            case_id,
            by_reviewer,
        )
