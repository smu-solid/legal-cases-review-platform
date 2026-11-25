"""Incremental allocation input assembly: classify existing work, build reviewer inputs, plan.

The read side of incremental allocation. It loads the published base run, classifies
existing assignments by movement class (submitted/claimed/draft/unclaimed), resolves the
reviewer pool (activity, authorization, capacity weight), guards against source-snapshot
drift, and drives the pure
:class:`review_platform.review.incremental_planner.IncrementalPlanner`. The persist and
publish mixins compose over this."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.allocation.eligible_units import CaseUnits, EligibleUnit
from review_platform.review.allocation.schemas import IncrementalPolicyInput
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.incremental_planner import (
    ExistingAssignment,
    IncrementalAllocationPreview,
    IncrementalPlanner,
    IncrementalPolicy,
    IncrementalReviewer,
    MovementPolicy,
)
from review_platform.review.models import (
    AllocationRun,
    AnnotationRevision,
    Assignment,
    AssignmentPlan,
    ReviewerPoolMember,
    ReviewItemAnswer,
    ReviewUnit,
)

# How hard it is to move an existing assignment, ascending. ``submitted`` never moves; ``draft``
# and ``claimed`` move only when the movement policy opts in; ``unclaimed`` is freely movable.
# Used to reduce a case's per-unit classes to the single class that governs the whole case.
_IMMOVABILITY = {"unclaimed": 0, "claimed": 1, "draft": 2, "submitted": 3}


def _live_campaign_assignment_rows(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]]:
    rows = session.execute(
        select(
            Assignment.id,
            Assignment.review_unit_id,
            Assignment.reviewer_id,
            Assignment.status,
        )
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == Assignment.tenant_id)
            & (ReviewUnit.id == Assignment.review_unit_id),
        )
        .where(
            Assignment.tenant_id == tenant_id,
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == campaign_id,
            assignment_is_live(),
        )
    ).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def _answer_assignment_ids(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(ReviewItemAnswer.assignment_id)
            .join(
                Assignment,
                (Assignment.tenant_id == ReviewItemAnswer.tenant_id)
                & (Assignment.id == ReviewItemAnswer.assignment_id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                Assignment.tenant_id == tenant_id,
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
                assignment_is_live(),
            )
            .distinct()
        )
    )


def _annotation_assignment_ids(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(AnnotationRevision.assignment_id)
            .join(
                Assignment,
                (Assignment.tenant_id == AnnotationRevision.tenant_id)
                & (Assignment.id == AnnotationRevision.assignment_id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                AnnotationRevision.tenant_id == tenant_id,
                Assignment.tenant_id == tenant_id,
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
                assignment_is_live(),
            )
            .distinct()
        )
    )


class AllocationIncrementalInputsMixin(AllocationServiceBase):
    """Loads and classifies the existing campaign state, then runs the pure planner."""

    def _classify_existing_assignments(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        unit_ids: set[uuid.UUID],
        case_by_unit: dict[uuid.UUID, str],
    ) -> list[ExistingAssignment]:
        """Return existing ``(case, reviewer)`` assignments, classified by movement class.

        Scoped by the caller's already-resolved eligible units rather than by re-deriving a
        ``review_kind``/``subject_kind`` filter here. The two must agree: an existing
        assignment the     planner cannot see makes its subject look uncovered and the
        planner provisions a fresh     reviewer on top of one that is then kept.
        Re-filtering on a single ``review_kind`` did     exactly that for any campaign
        whose units are not all that kind -- it silently hid the     campaign's real
        coverage.

        Assignments are aggregated to the CASE, because the allocation subject is the case
        (as on     the initial path). A reviewer holding any unit of a case counts as
        holding that case, and     the case takes the *least movable* class across those
        units: a case containing submitted     work is immovable as a whole, so
        rebalancing can never strand a half-reviewed case."""

        if not unit_ids:
            return []
        campaign_rows = _live_campaign_assignment_rows(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        # Loading by campaign keeps the SQL parameter count constant. The planner may operate on a
        # narrower eligible projection, so filter to its exact unit IDs before classification.
        rows = [row for row in campaign_rows if row[1] in unit_ids]

        answer_assignment_ids = _answer_assignment_ids(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        annotation_assignment_ids = _annotation_assignment_ids(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

        by_case_reviewer: dict[tuple[str, str], str] = {}
        for assignment_id, unit_id, reviewer_id, status in rows:
            if status == "submitted":
                mc = "submitted"
            else:
                # "claimed" — promote to "draft" when the reviewer has started any work.
                has_saved_work = (
                    assignment_id in answer_assignment_ids
                    or assignment_id in annotation_assignment_ids
                )
                mc = "draft" if has_saved_work else "claimed"
            # Collapse the case's units into one (case, reviewer) entry, keeping the least movable
            # class seen so far -- the strongest constraint any of its units imposes.
            key = (case_by_unit.get(unit_id, f"unit:{unit_id}"), str(reviewer_id))
            previous = by_case_reviewer.get(key)
            if previous is None or _IMMOVABILITY[mc] > _IMMOVABILITY[previous]:
                by_case_reviewer[key] = mc

        result: list[ExistingAssignment] = [
            ExistingAssignment(
                subject_id=case_key,
                reviewer_id=reviewer_id,
                movement_class=movement_class,  # type: ignore[arg-type]
            )
            for (case_key, reviewer_id), movement_class in by_case_reviewer.items()
        ]
        return result

    def _incremental_reviewer_inputs(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        reviewer_ids: list[uuid.UUID],
        capacity_weights: dict[str, float],
        pool_members: list[ReviewerPoolMember],
    ) -> list[IncrementalReviewer]:
        rows = session.execute(
            select(TenantMembership.user_id, RoleGrant.id, User.status, TenantMembership.status)
            .select_from(TenantMembership)
            .join(User, User.id == TenantMembership.user_id)
            .outerjoin(
                RoleGrant,
                (RoleGrant.membership_id == TenantMembership.id)
                & (RoleGrant.role_code == "reviewer")
                & (RoleGrant.revoked_at.is_(None)),
            )
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id.in_(reviewer_ids),
            )
        ).all()
        by_user = {row[0]: row for row in rows}
        member_weights = {m.reviewer_id: m.capacity_weight for m in pool_members}
        reviewers: list[IncrementalReviewer] = []
        for reviewer_id in reviewer_ids:
            row = by_user.get(reviewer_id)
            weight = capacity_weights.get(str(reviewer_id)) or member_weights.get(reviewer_id, 1.0)
            if row is None:
                reviewers.append(
                    IncrementalReviewer(
                        reviewer_id=str(reviewer_id),
                        active=False,
                        authorized=False,
                        capacity_weight=weight,
                    )
                )
                continue
            _, role_grant_id, user_status, membership_status = row
            reviewers.append(
                IncrementalReviewer(
                    reviewer_id=str(reviewer_id),
                    active=membership_status == "active" and user_status == "active",
                    authorized=role_grant_id is not None,
                    capacity_weight=weight,
                )
            )
        return reviewers

    def _load_base_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        base_run_id: uuid.UUID,
    ) -> AllocationRun:
        run = session.scalar(
            select(AllocationRun).where(
                AllocationRun.tenant_id == tenant_id,
                AllocationRun.campaign_id == campaign_id,
                AllocationRun.id == base_run_id,
                AllocationRun.status == "published",
            )
        )
        if run is None:
            raise APIError(
                404,
                "base_run_not_found",
                "Base run not found",
                "The base allocation run does not exist or has not been published.",
            )
        return run

    def _incremental_plan(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: IncrementalPolicyInput,
        base_run: AllocationRun,
    ) -> tuple[
        IncrementalAllocationPreview,
        list[EligibleUnit],
        CaseUnits,
    ]:
        units = self._eligible_units(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            subject_kind=body.subject_kind,
            review_kind=body.review_kind,
        )
        current_unit_ids = {unit.review_unit_id for unit in units}
        recorded_ids = (base_run.summary_json or {}).get("source_unit_ids")
        if isinstance(recorded_ids, list) and all(isinstance(value, str) for value in recorded_ids):
            base_unit_ids = {uuid.UUID(value) for value in recorded_ids}
        else:
            # Compatibility for already-published production runs created before source IDs were
            # persisted explicitly. A successful initial run has one or more plans per source unit.
            base_unit_ids = set(
                session.scalars(
                    select(AssignmentPlan.review_unit_id)
                    .where(
                        AssignmentPlan.tenant_id == tenant_id,
                        AssignmentPlan.allocation_run_id == base_run.id,
                    )
                    .distinct()
                )
            )
        # Completion does not remove an input: these units (and other units of the
        # same blocked subject) leave eligibility but remain in the campaign. Keep
        # scope/identity drift checks for every other baseline unit.
        blocked_subjects = select(ReviewUnit.review_subject_id).where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == campaign_id,
            ReviewUnit.status.in_(("in_adjudication", "resolved")),
        )
        completed_unit_ids = set(
            session.scalars(
                select(ReviewUnit.id).where(
                    ReviewUnit.tenant_id == tenant_id,
                    ReviewUnit.campaign_id == campaign_id,
                    or_(
                        ReviewUnit.status.in_(("in_adjudication", "resolved")),
                        ReviewUnit.review_subject_id.in_(blocked_subjects),
                    ),
                )
            )
        )
        if not base_unit_ids.issubset(current_unit_ids | completed_unit_ids):
            raise APIError(
                409,
                "blocked_by_snapshot_drift",
                "Blocked by snapshot drift",
                "Existing campaign units were removed or replaced since the base run. Appended "
                "units are supported, but destructive scope drift requires a new campaign.",
            )
        # Case-native, exactly as on the initial path: the allocation subject is the whole case, so
        # rebalancing moves a case with every one of its in-scope units. Planning per review unit
        # instead let a rebalance split one case across more reviewers than ``min_reviews`` -- each
        # unit still had the right number, but no reviewer held the whole case, which is the
        # invariant ``test_case_native_allocation`` exists to protect.
        case_units = self._group_units_by_case(units)
        subject_ids = tuple(case_units.keys())
        existing = self._classify_existing_assignments(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            unit_ids=current_unit_ids,
            case_by_unit={
                unit.review_unit_id: case_key
                for case_key, members in case_units.items()
                for unit in members
            },
        )
        pool_members = list(
            session.scalars(
                select(ReviewerPoolMember).where(
                    ReviewerPoolMember.tenant_id == tenant_id,
                    ReviewerPoolMember.reviewer_pool_id == base_run.reviewer_pool_id,
                )
            )
        )
        reviewers = self._incremental_reviewer_inputs(
            session,
            tenant_id=tenant_id,
            reviewer_ids=body.reviewer_ids,
            capacity_weights=dict(body.reviewer_capacity_weights),
            pool_members=pool_members,
        )
        mp = body.movement_policy
        policy = IncrementalPolicy(
            min_reviews_per_subject=body.min_reviews_per_subject,
            max_workload_per_reviewer=body.max_workload_per_reviewer,
            movement_policy=MovementPolicy(
                allow_rebalance_unclaimed=mp.allow_rebalance_unclaimed,
                allow_rebalance_claimed=mp.allow_rebalance_claimed,
                allow_rebalance_draft=mp.allow_rebalance_draft,
            ),
            random_seed=body.random_seed,
            allocation_policy_version=body.allocation_policy_version,
        )
        previous_reviewer_ids = tuple(str(m.reviewer_id) for m in pool_members)
        preview = IncrementalPlanner().plan(
            subject_ids=subject_ids,
            reviewers=tuple(reviewers),
            existing_assignments=tuple(existing),
            policy=policy,
            previous_reviewer_ids=previous_reviewer_ids,
        )
        return preview, units, case_units
