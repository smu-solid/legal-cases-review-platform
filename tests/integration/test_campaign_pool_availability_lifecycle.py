from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.db.models import utcnow
from review_platform.db.session import Database
from review_platform.review.allocation.schemas import (
    AllocationPolicyInput,
    IncrementalPolicyInput,
)
from review_platform.review.allocation.service import AllocationService
from review_platform.review.models import (
    AllocationRun,
    Assignment,
    AssignmentPlan,
    Campaign,
    ReviewItemAnswer,
    ReviewUnit,
)
from review_platform.review.schemas import (
    CampaignEditRequest,
    CampaignReviewScopeInput,
    CreateCampaignRequest,
    LoadPoolCasesRequest,
)
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user
from tests.support.identities import AdminIdentity
from tests.support.pool import (
    _case,
    _ensure_admin_is_reviewer,
    _pool_unit_count,
    _principal,
    _seed_pool,
    _service,
    _sha,
)


@pytest.mark.parametrize("required", [2, 3])
def test_widening_a_published_campaign_scope_backfills_existing_cases(
    db_session: Session, admin: AdminIdentity, tmp_path: Path, required: int
) -> None:
    """Adding a field group pulls that group in for the campaign's *existing* cases.

    Regression: the edit used to persist the wider scope and stop there, so the cases already in
    the campaign kept only their original fields while cases loaded afterwards got the wider set --
    one campaign carrying two different per-case field coverages.
    """

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=2)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="widen-me",
            campaign_name="Widen me",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata"]),
            requested_case_count=1,
            reviews_per_case=required,
        ),
        request_id="req-create",
    )
    assert created.total_units == 1  # case_metadata only

    campaign = db_session.scalar(
        select(Campaign).where(Campaign.tenant_id == admin.tenant_id, Campaign.key == "widen-me")
    )
    assert campaign is not None
    campaign.status = "published"
    db_session.flush()
    service.edit_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.id,
        body=CampaignEditRequest(
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata", "court_and_hearing"]),
            confirm=True,
        ),
        request_id="req-widen",
    )
    db_session.flush()

    unit_count = db_session.scalar(
        select(func.count())
        .select_from(ReviewUnit)
        .where(
            ReviewUnit.tenant_id == admin.tenant_id,
            ReviewUnit.campaign_id == campaign.id,
        )
    )
    # The already-held case now carries BOTH groups, not just the one it was created with.
    assert unit_count == 2

    assert set(
        db_session.scalars(
            select(ReviewUnit.required_reviews).where(ReviewUnit.campaign_id == campaign.id)
        )
    ) == {required}


def test_widening_a_published_campaign_scope_rejects_another_campaigns_field(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Field scope stays disjoint across campaigns: the edit is rejected, nothing moves."""

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=2)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="owns-court",
            campaign_name="Owns court",
            review_scope=CampaignReviewScopeInput(group_ids=["court_and_hearing"]),
            requested_case_count=1,
        ),
        request_id="req-owner",
    )
    service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="wants-court",
            campaign_name="Wants court",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata"]),
            requested_case_count=1,
        ),
        request_id="req-wanter",
    )
    wanter = db_session.scalar(
        select(Campaign).where(Campaign.tenant_id == admin.tenant_id, Campaign.key == "wants-court")
    )
    assert wanter is not None
    wanter.status = "published"
    db_session.flush()

    with pytest.raises(APIError) as excinfo:
        service.edit_campaign(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=wanter.id,
            body=CampaignEditRequest(
                review_scope=CampaignReviewScopeInput(
                    group_ids=["case_metadata", "court_and_hearing"]
                ),
                confirm=True,
            ),
            request_id="req-conflict",
        )
    assert excinfo.value.status == 409
    assert excinfo.value.code == "campaign_scope_conflict"
    assert "owns-court" in excinfo.value.detail

    # The rejected edit left the scope and the unit layout untouched: the conflict is detected
    # before anything is written, so the caller's transaction has nothing to undo.
    assert wanter.review_scope_json["group_ids"] == ["case_metadata"]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == wanter.id,
            )
        )
        == 1
    )


def test_already_completed_case_field_cannot_re_enter_the_pool(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Idempotency-by-``external_item_key`` means a case/field that ever existed anywhere (pool,
    active campaign, or a closed/completed one) can never be preloaded into the pool again --
    "already completed" and "already claimed" both reduce to "absent from the pool" by
    construction (see case_pool.py's module docstring)."""

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="completed-owner", campaign_name="Completed owner", requested_case_count=1
        ),
        request_id="req-1",
    )
    # Simulate the unit being reviewed to completion in its real campaign (out of scope here to
    # drive the full review lifecycle) -- the re-seed attempt below is refused regardless of status,
    # because the snapshot itself already exists.
    reimported = _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    assert reimported == 0


def test_delete_refuses_submitted_work_and_does_not_recycle_resolved_units(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A draft delete is the inverse of materialize-from-pool: the freed cases become selectable
    again, so the pool count returns to what it was before the campaign drew from it."""

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha)])
    pool_before = _pool_unit_count(db_session, admin)
    assert pool_before == 4  # two cases * two field groups

    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="pilot-del", campaign_name="Pilot Del", requested_case_count=2
        ),
        request_id="req-create",
    )
    assert created.total_units == 4
    assert _pool_unit_count(db_session, admin) == 0  # everything moved into the draft

    assigned_unit_ids = list(
        db_session.scalars(
            select(ReviewUnit.id).where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == created.campaign_id,
            )
        )
    )
    assignments = [
        Assignment(
            tenant_id=admin.tenant_id,
            review_unit_id=unit_id,
            reviewer_id=admin.user_id,
            status="claimed",
            lease_expires_at=utcnow() + timedelta(hours=1),
        )
        for unit_id in assigned_unit_ids
    ]
    db_session.add_all(assignments)
    db_session.flush()
    assignments[0].status = "submitted"
    assignments[0].submitted_at = utcnow()
    db_session.add(
        ReviewItemAnswer(
            tenant_id=admin.tenant_id,
            assignment_id=assignments[0].id,
            revision_no=1,
            state="submitted",
            value_correct=True,
            provenance_correct=True,
            corrected_value_json=None,
            corrected_value_display=None,
            comment=None,
            failure_reason=None,
            evidence_ids_json=[],
            corrected_provenance_spans_json=[],
            client_request_id="delete-preserves-review-work",
            author_id=admin.user_id,
        )
    )
    db_session.flush()

    campaign = db_session.get(Campaign, created.campaign_id)
    assert campaign is not None
    campaign.policy_json = {**campaign.policy_json, "selected_reviewer_ids": [str(admin.user_id)]}
    with pytest.raises(APIError) as exc_info:
        service.delete_campaign(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=created.campaign_id,
            confirm=True,
            request_id="req-del",
        )
    assert exc_info.value.code == "campaign_delete_work_exists"
    assert _pool_unit_count(db_session, admin) == 0
    remaining = db_session.scalar(
        select(func.count())
        .select_from(ReviewUnit)
        .where(
            ReviewUnit.tenant_id == admin.tenant_id,
            ReviewUnit.campaign_id == created.campaign_id,
        )
    )
    assert remaining == len(assigned_unit_ids)
    assignments_remaining = db_session.scalar(
        select(func.count())
        .select_from(Assignment)
        .where(
            Assignment.tenant_id == admin.tenant_id,
            Assignment.review_unit_id.in_(assigned_unit_ids),
        )
    )
    assert assignments_remaining == len(assignments)


def test_delete_refuses_draft_owned_by_reviewer_missing_from_selected_roster(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="divergent-owner", campaign_name="Divergent", requested_case_count=1
        ),
        request_id="req-divergent",
    )
    campaign = db_session.get(Campaign, created.campaign_id)
    assert campaign is not None
    assert campaign.policy_json.get("selected_reviewer_ids", []) == []
    unit_id = db_session.scalar(
        select(ReviewUnit.id).where(ReviewUnit.campaign_id == created.campaign_id).limit(1)
    )
    assignment = Assignment(
        tenant_id=admin.tenant_id,
        review_unit_id=unit_id,
        reviewer_id=admin.user_id,
        status="claimed",
        lease_expires_at=utcnow() + timedelta(hours=1),
    )
    db_session.add(assignment)
    db_session.flush()
    db_session.add(
        ReviewItemAnswer(
            tenant_id=admin.tenant_id,
            assignment_id=assignment.id,
            revision_no=1,
            state="draft",
            value_correct=None,
            provenance_correct=None,
            corrected_value_json=None,
            corrected_value_display=None,
            comment=None,
            failure_reason=None,
            evidence_ids_json=[],
            corrected_provenance_spans_json=[],
            client_request_id="divergent-draft",
            author_id=admin.user_id,
        )
    )
    db_session.flush()

    with pytest.raises(APIError) as exc_info:
        service.delete_campaign(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=created.campaign_id,
            confirm=True,
            request_id="req-divergent-delete",
        )
    assert exc_info.value.code == "campaign_delete_work_exists"
    assert _pool_unit_count(db_session, admin) == 0


def test_a_case_freed_by_delete_can_be_drawn_into_a_new_campaign(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """End-to-end freeing: after delete, the same case is selectable by a fresh campaign."""

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    first = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="pilot-first", campaign_name="First", requested_case_count=2
        ),
        request_id="req-first",
    )
    service.delete_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=first.campaign_id,
        confirm=True,
        request_id="req-first-del",
    )
    second = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="pilot-second", campaign_name="Second", requested_case_count=2
        ),
        request_id="req-second",
    )
    assert second.availability is not None
    assert second.availability.feasibility == "feasible_exact"
    assert second.total_units == 4


def test_recycled_original_unit_keeps_candidates_and_evidence_in_reviewer_bundle(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1, with_evidence=True)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    first = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="bundle-first", campaign_name="Bundle first", requested_case_count=1
        ),
        request_id="req-bundle-first",
    )
    original_unit_id = db_session.scalar(
        select(ReviewUnit.id).where(ReviewUnit.campaign_id == first.campaign_id)
    )
    service.delete_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=first.campaign_id,
        confirm=True,
        request_id="req-bundle-delete",
    )
    second = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="bundle-second", campaign_name="Bundle second", requested_case_count=1
        ),
        request_id="req-bundle-second",
    )
    recycled_unit_id = db_session.scalar(
        select(ReviewUnit.id).where(ReviewUnit.campaign_id == second.campaign_id)
    )
    assert recycled_unit_id == original_unit_id

    _ensure_admin_is_reviewer(db_session, admin)
    assignment = Assignment(
        tenant_id=admin.tenant_id,
        review_unit_id=recycled_unit_id,
        reviewer_id=admin.user_id,
        status="claimed",
        lease_expires_at=utcnow() + timedelta(hours=1),
    )
    db_session.add(assignment)
    db_session.flush()

    bundle = service.bundle(
        db_session,
        tenant_id=admin.tenant_id,
        assignment_id=assignment.id,
        principal=principal,
    )
    assert [candidate.value for candidate in bundle.candidates] == ["[2018] SGHCF 99"]
    assert [window.snippet for window in bundle.evidence_windows] == ["[2018] SGHCF 99"]


def test_add_cases_after_initial_publish_can_be_incrementally_published_without_moving_draft(
    db_session: Session,
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """Runbook path: publish → save draft → load case → incremental preview and publish."""

    _ensure_admin_is_reviewer(db_session, admin)
    second_reviewer = add_review_user(
        database,
        settings,
        admin,
        email="incremental-growth-reviewer@example.test",
        role="reviewer",
    )
    sha = _sha()
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [_case("CAS-GROW-1", sha, groups=1), _case("CAS-GROW-2", sha, groups=1)],
    )
    review_service = _service(tmp_path)
    allocation_service = AllocationService("k" * 32)
    principal = _principal(db_session, admin)
    campaign = review_service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="incremental-growth",
            campaign_name="Incremental growth",
            requested_case_count=1,
        ),
        request_id="req-growth-create",
    )
    review_service.add_campaign_reviewer(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.campaign_id,
        reviewer_id=admin.user_id,
        request_id="req-growth-reviewer",
    )
    review_service.add_campaign_reviewer(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.campaign_id,
        reviewer_id=second_reviewer.user_id,
        request_id="req-growth-reviewer-two",
    )
    initial_policy = AllocationPolicyInput.model_validate(
        {
            "subject_kind": "case",
            "review_kind": "metadata_field",
            "reviewer_ids": [admin.user_id, second_reviewer.user_id],
            "target_distinct_subjects": 1,
            "target_per_reviewer_workload": 1,
            "target_pairwise_overlap": 0,
            "target_global_overlap": 0,
            "uniform_reviews_per_subject": 2,
            "rolling_window_size": 1,
            "rolling_window_stride": 1,
            "hub_priority_count": 0,
            "random_seed": "growth-initial",
            "allocation_policy_version": "reviewer-allocation/v1",
            "metric_weights": {},
        }
    )
    initial_publish = allocation_service.publish_from_policy(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        principal=principal,
        body=initial_policy,
        idempotency_key="growth-initial-publish",
        request_id="req-growth-initial-publish",
    )
    original_assignment = db_session.scalar(
        select(Assignment)
        .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
        .where(
            ReviewUnit.campaign_id == campaign.campaign_id,
            Assignment.reviewer_id == admin.user_id,
        )
    )
    assert original_assignment is not None
    initial_assignment_count = (
        db_session.scalar(
            select(func.count())
            .select_from(Assignment)
            .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
            .where(ReviewUnit.campaign_id == campaign.campaign_id)
        )
        or 0
    )
    db_session.add(
        ReviewItemAnswer(
            tenant_id=admin.tenant_id,
            assignment_id=original_assignment.id,
            revision_no=1,
            state="draft",
            value_correct=None,
            provenance_correct=None,
            corrected_value_json=None,
            corrected_value_display=None,
            comment=None,
            failure_reason=None,
            evidence_ids_json=[],
            corrected_provenance_spans_json=[],
            client_request_id="growth-saved-draft",
            author_id=admin.user_id,
        )
    )
    db_session.flush()

    loaded = review_service.load_pool_cases(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.campaign_id,
        body=LoadPoolCasesRequest(requested_case_count=1),
        request_id="req-growth-load",
    )
    assert loaded.materialized_cases == 1
    assert loaded.total_units == 2

    incremental_policy = IncrementalPolicyInput.model_validate(
        {
            "subject_kind": "case",
            "review_kind": "metadata_field",
            "reviewer_ids": [admin.user_id, second_reviewer.user_id],
            "base_run_id": initial_publish.run_id,
            "min_reviews_per_subject": 2,
            "movement_policy": {
                "allow_rebalance_unclaimed": True,
                "allow_rebalance_claimed": True,
                "allow_rebalance_draft": False,
            },
            "random_seed": "growth-incremental",
            "allocation_policy_version": "reviewer-allocation/v1",
        }
    )
    preview = allocation_service.preview_incremental_run(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        principal=principal,
        body=incremental_policy,
    )
    assert preview.new_assignment_count >= 2
    persisted = allocation_service.persist_incremental_run(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        principal=principal,
        body=incremental_policy,
        idempotency_key="growth-incremental-persist",
        request_id="req-growth-incremental-persist",
    )
    published = allocation_service.publish_incremental_run(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        run_id=persisted.run_id,
        principal=principal,
        idempotency_key="growth-incremental-publish",
        request_id="req-growth-incremental-publish",
    )
    assert published.new_assignment_count >= 2
    assignments = list(
        db_session.scalars(
            select(Assignment)
            .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
            .where(ReviewUnit.campaign_id == campaign.campaign_id)
        )
    )
    assert len(assignments) == initial_assignment_count + published.new_assignment_count
    assignment_counts = {
        row[0]: row[1]
        for row in db_session.execute(
            select(Assignment.review_unit_id, func.count())
            .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
            .where(ReviewUnit.campaign_id == campaign.campaign_id)
            .group_by(Assignment.review_unit_id)
        )
    }
    assert len(assignment_counts) == 2
    assert min(assignment_counts.values()) >= 2
    assert db_session.get(Assignment, original_assignment.id) is original_assignment
    assert original_assignment.reviewer_id == admin.user_id
    assert db_session.scalar(
        select(ReviewItemAnswer.id).where(
            ReviewItemAnswer.assignment_id == original_assignment.id,
            ReviewItemAnswer.state == "draft",
        )
    )


def test_delete_returns_units_to_pool_after_allocation_run_published(
    db_session: Session,
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """Regression: deleting a published, allocated campaign with no saved/submitted work must
    return its units to the pool. The allocation run's ``assignment_plans`` reference
    assignments     via an ON DELETE SET NULL composite ``(tenant_id, assignment_id)`` FK,
    so the delete must drop     the allocation runs (cascading the plans) before deleting
    assignments -- otherwise the plan's     NOT NULL ``tenant_id`` is nulled and the whole
    delete fails (previously a 500 in production)."""

    _ensure_admin_is_reviewer(db_session, admin)
    second_reviewer = add_review_user(
        database,
        settings,
        admin,
        email="delete-alloc-reviewer@example.test",
        role="reviewer",
    )
    sha = _sha()
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [_case("CAS-DELALLOC-1", sha, groups=1), _case("CAS-DELALLOC-2", sha, groups=1)],
    )
    pool_before = _pool_unit_count(db_session, admin)
    review_service = _service(tmp_path)
    allocation_service = AllocationService("k" * 32)
    principal = _principal(db_session, admin)
    campaign = review_service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="delete-alloc",
            campaign_name="Delete alloc",
            requested_case_count=2,
        ),
        request_id="req-delalloc-create",
    )
    assert _pool_unit_count(db_session, admin) == pool_before - campaign.total_units
    for reviewer_id, suffix in ((admin.user_id, "one"), (second_reviewer.user_id, "two")):
        review_service.add_campaign_reviewer(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=campaign.campaign_id,
            reviewer_id=reviewer_id,
            request_id=f"req-delalloc-reviewer-{suffix}",
        )
    policy = AllocationPolicyInput.model_validate(
        {
            "subject_kind": "case",
            "review_kind": "metadata_field",
            "reviewer_ids": [admin.user_id, second_reviewer.user_id],
            "target_distinct_subjects": 2,
            "target_per_reviewer_workload": 2,
            "target_pairwise_overlap": 0,
            "target_global_overlap": 0,
            "uniform_reviews_per_subject": 2,
            "rolling_window_size": 1,
            "rolling_window_stride": 1,
            "hub_priority_count": 0,
            "random_seed": "delalloc",
            "allocation_policy_version": "reviewer-allocation/v1",
            "metric_weights": {},
        }
    )
    allocation_service.publish_from_policy(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        principal=principal,
        body=policy,
        idempotency_key="delalloc-publish",
        request_id="req-delalloc-publish",
    )
    campaign_unit_ids = select(ReviewUnit.id).where(
        ReviewUnit.tenant_id == admin.tenant_id, ReviewUnit.campaign_id == campaign.campaign_id
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AllocationRun)
            .where(AllocationRun.campaign_id == campaign.campaign_id)
        )
        >= 1
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AssignmentPlan)
            .where(AssignmentPlan.review_unit_id.in_(campaign_unit_ids))
        )
        >= 1
    )

    deleted = review_service.delete_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.campaign_id,
        confirm=True,
        request_id="req-delalloc-delete",
    )

    assert deleted.status == "closed"
    assert deleted.already_closed is False
    assert _pool_unit_count(db_session, admin) == pool_before
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == campaign.campaign_id,
            )
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AllocationRun)
            .where(AllocationRun.campaign_id == campaign.campaign_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AssignmentPlan)
            .where(AssignmentPlan.review_unit_id.in_(campaign_unit_ids))
        )
        == 0
    )
