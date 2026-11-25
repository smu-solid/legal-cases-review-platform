"""Shared base for the allocation service: authorization, idempotency, loading, and planning.

The operation mixins (planning/persist, lifecycle, queries) compose over this base, which owns the
helpers they share: RBAC, tenant scope, idempotency records, entity loaders, the reviewer/subject
inputs, and the call into the pure :class:`AllocationPlanner`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from review_platform.auth.grant_policy import has_global_admin
from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.allocation import (
    AllocationPlanner,
    AllocationPolicy,
    AllocationPreview,
    AllocationReviewer,
    AllocationSubject,
)
from review_platform.review.allocation.counts import run_assignment_counts
from review_platform.review.allocation.eligible_units import (
    CaseUnits,
    EligibleUnit,
    allocation_case_key,
)
from review_platform.review.allocation.schemas import AllocationPolicyInput, AssignmentCountsOut
from review_platform.review.allocation.selection import subject_metrics
from review_platform.review.grouping import classify_unit
from review_platform.review.idempotency import IdempotencyMixin
from review_platform.review.models import (
    AllocationRun,
    Campaign,
    ReviewSubject,
    ReviewUnit,
)


class AllocationServiceBase(IdempotencyMixin):
    def __init__(self, audit_key: str) -> None:
        self.audit_key = audit_key
        self.planner = AllocationPlanner()

    # -- authorization / idempotency / scope helpers --------------------------------------------

    def _require_campaign_manager(
        self, session: Session, principal: Principal, tenant_id: uuid.UUID
    ) -> None:
        if has_global_admin(session, principal.user.id):
            return
        allowed = session.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == principal.user.id,
                TenantMembership.status == "active",
                RoleGrant.role_code == "campaign_manager",
                RoleGrant.revoked_at.is_(None),
            )
        )
        if not allowed:
            raise APIError(403, "forbidden", "Forbidden", "The action is not permitted.")

    # -- shared loading / planning --------------------------------------------------------------

    def _load_campaign(
        self, session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> Campaign:
        campaign = session.scalar(
            select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
        )
        if campaign is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return campaign

    @staticmethod
    def _eligible_units(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        subject_kind: str,
        review_kind: str,
    ) -> list[EligibleUnit]:
        campaign = session.scalar(
            select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
        )
        blocked_subject_unit = aliased(ReviewUnit)
        subject_blocked = exists(
            select(1).where(
                blocked_subject_unit.tenant_id == tenant_id,
                blocked_subject_unit.campaign_id == campaign_id,
                blocked_subject_unit.review_subject_id == ReviewUnit.review_subject_id,
                blocked_subject_unit.status.in_(("in_adjudication", "resolved")),
            )
        )
        case_id = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
        citation_metrics = ReviewSubject.attributes_json["citation_metrics"]
        rows = session.execute(
            select(
                ReviewUnit.id.label("review_unit_id"),
                ReviewUnit.review_subject_id,
                ReviewUnit.tenant_id,
                ReviewUnit.campaign_id,
                ReviewUnit.status,
                ReviewSubject.subject_kind,
                ReviewUnit.review_kind,
                ReviewUnit.safe_field_label,
                ReviewUnit.field_name,
                case_id.label("snapshot_local_case_external_id"),
                ReviewSubject.external_subject_id,
                citation_metrics.label("citation_metrics"),
                ReviewSubject.display_title,
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
                ReviewUnit.status.in_(("pending", "in_review")),
                ~subject_blocked,
                ReviewSubject.subject_kind == subject_kind,
            )
            .order_by(ReviewUnit.id)
        ).mappings()
        units = [EligibleUnit(**row) for row in rows]
        # Case-native allocation: the allocation subject is the whole case, so its eligible pool
        # spans every in-scope field of the case regardless of ``review_kind`` (metadata_field,
        # cited_case, statute_reference, ...). The campaign's ``review_scope_json`` (group_ids /
        # review_kinds selected by the admin) is the authoritative filter. A campaign with no
        # declared scope (e.g. "All fields" in the admin UI, which stores review_scope_json = NULL)
        # means no review_kind narrowing at all -- every in-scope unit of the case is eligible,
        # consistent with materialization (_materialize_from_pool, grouped_bundle, queue). This also
        # repairs already-created NULL-scope campaigns without a data migration.
        if campaign is None or not campaign.review_scope_json:
            return units
        group_ids = set(campaign.review_scope_json.get("group_ids") or [])
        review_kinds = set(campaign.review_scope_json.get("review_kinds") or [])
        return [
            unit
            for unit in units
            if (
                not group_ids
                or classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name).group_id
                in group_ids
            )
            and (not review_kinds or unit.review_kind in review_kinds)
        ]

    @staticmethod
    def _case_key(subject: ReviewSubject) -> str:
        """Stable case identity for case-native allocation.

        Every field/relation of a case is a distinct ``ReviewSubject`` tagged with the case's own
        external id in ``attributes_json["snapshot_local_case_external_id"]`` (see
        ``review_platform.review.campaign_conflicts``). That tag is the allocation-subject key.
        Fall back to the subject's own external id if the case tag is ever absent, so a mistagged
        row degrades to a one-field case rather than colliding with another case.
        """

        return allocation_case_key(
            case_id=(subject.attributes_json or {}).get("snapshot_local_case_external_id"),
            external_subject_id=subject.external_subject_id,
            review_subject_id=subject.id,
        )

    @classmethod
    def _group_units_by_case(cls, units: list[EligibleUnit]) -> CaseUnits:
        """Group eligible units into ordered per-case buckets keyed by :meth:`_case_key`.

        Insertion order follows ``units`` (already ordered by ``ReviewUnit.id``), so allocation
        remains deterministic for a fixed candidate pool.
        """

        case_units: CaseUnits = {}
        for unit in units:
            case_units.setdefault(unit.case_key, []).append(unit)
        return case_units

    def _run_assignment_counts(
        self, session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
    ) -> AssignmentCountsOut:
        return run_assignment_counts(session, tenant_id=tenant_id, run_id=run_id)

    def _case_keys_for_units(
        self, session: Session, *, tenant_id: uuid.UUID, unit_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Map review-unit ids to their :meth:`_case_key`.

        The incremental path plans per review unit, so its new/moved counts are unit-level; this is
        what lets those same movements also be reported as ``(case, reviewer)`` pairs.
        """

        if not unit_ids:
            return {}
        rows = session.execute(
            select(ReviewUnit.id, ReviewSubject)
            .select_from(ReviewUnit)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.id.in_(unit_ids))
        ).all()
        return {unit_id: self._case_key(subject) for unit_id, subject in rows}

    @staticmethod
    def _snapshot_digest(units: list[EligibleUnit]) -> str:
        """Identity of the candidate pool, used to detect drift between persist and publish."""

        return digest_json(sorted(str(unit.review_unit_id) for unit in units))

    @staticmethod
    def _pool_digest(reviewer_ids: list[uuid.UUID]) -> str:
        return digest_json(sorted(str(value) for value in reviewer_ids))

    def _reviewer_inputs(
        self, session: Session, *, tenant_id: uuid.UUID, reviewer_ids: list[uuid.UUID]
    ) -> list[AllocationReviewer]:
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
        reviewers: list[AllocationReviewer] = []
        for reviewer_id in reviewer_ids:
            row = by_user.get(reviewer_id)
            if row is None:
                reviewers.append(
                    AllocationReviewer(reviewer_id=str(reviewer_id), active=False, authorized=False)
                )
                continue
            _, role_grant_id, user_status, membership_status = row
            reviewers.append(
                AllocationReviewer(
                    reviewer_id=str(reviewer_id),
                    active=membership_status == "active" and user_status == "active",
                    authorized=role_grant_id is not None,
                )
            )
        return reviewers

    def _plan(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        policy_input: AllocationPolicyInput,
    ) -> tuple[
        AllocationPreview,
        list[EligibleUnit],
        CaseUnits,
    ]:
        units = self._eligible_units(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            subject_kind=policy_input.subject_kind,
            review_kind=policy_input.review_kind,
        )
        case_units = self._group_units_by_case(units)
        subjects = [
            AllocationSubject(
                subject_id=case_key,
                subject_kind=policy_input.subject_kind,
                review_kind=policy_input.review_kind,
                metrics=subject_metrics(members[0]),
            )
            for case_key, members in case_units.items()
        ]
        reviewers = self._reviewer_inputs(
            session, tenant_id=tenant_id, reviewer_ids=policy_input.reviewer_ids
        )
        policy = AllocationPolicy(
            subject_kind=policy_input.subject_kind,
            review_kind=policy_input.review_kind,
            target_distinct_subjects=policy_input.target_distinct_subjects,
            target_per_reviewer_workload=policy_input.target_per_reviewer_workload,
            target_pairwise_overlap=policy_input.target_pairwise_overlap,
            target_global_overlap=policy_input.target_global_overlap,
            rolling_window_size=policy_input.rolling_window_size,
            rolling_window_stride=policy_input.rolling_window_stride,
            hub_priority_count=policy_input.hub_priority_count,
            random_seed=policy_input.random_seed,
            allocation_policy_version=policy_input.allocation_policy_version,
            metric_weights=dict(policy_input.metric_weights),
            uniform_reviews_per_subject=policy_input.uniform_reviews_per_subject,
        )
        return (
            self.planner.plan(subjects=subjects, reviewers=reviewers, policy=policy),
            units,
            case_units,
        )

    def _load_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        for_update: bool = False,
    ) -> AllocationRun:
        statement = select(AllocationRun).where(
            AllocationRun.tenant_id == tenant_id,
            AllocationRun.campaign_id == campaign_id,
            AllocationRun.id == run_id,
        )
        if for_update:
            statement = statement.with_for_update()
        run = session.scalar(statement)
        if run is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return run
