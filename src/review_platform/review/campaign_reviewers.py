"""Split out of ``review_platform.review.campaign_lifecycle`` to keep that file under the
repository's production-file size guardrail; reuses its ``_load_campaign_for_update``/
``_selected_reviewer_ids`` helpers so both files agree on where reviewer selection lives
(``Campaign.policy_json``)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.base import ReviewServiceBase
from review_platform.review.campaign_queries import (
    _load_campaign_for_update,
    _selected_reviewer_ids,
)
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Campaign,
    ReviewItemAnswer,
    ReviewUnit,
)
from review_platform.review.schemas import CampaignReviewersResponse

_REVIEWER_MANAGEABLE_STATUSES = frozenset({"draft", "planned", "published"})


def campaign_reviewer_work_exists(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    reviewer_id: uuid.UUID,
) -> bool:
    """True iff this reviewer has saved, submitted, or revision-requested work in this campaign.

    Module-level (not a mixin method) so both the remove-reviewer guard
    (``ReviewCampaignReviewersMixin._require_reviewer_has_no_work``) and the read-only workload
    summary (``ReviewAdminMixin.reviewer_workload``, in ``campaign_admin.py``) share one
    definition of "has work" -- the UI must never guess this ahead of the backend.
    """

    campaign_unit_ids = select(ReviewUnit.id).where(
        ReviewUnit.tenant_id == tenant_id,
        ReviewUnit.campaign_id == campaign_id,
    )
    reviewer_assignment_ids = select(Assignment.id).where(
        Assignment.tenant_id == tenant_id,
        Assignment.reviewer_id == reviewer_id,
        Assignment.review_unit_id.in_(campaign_unit_ids),
    )
    return bool(
        session.scalar(
            select(Assignment.id)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.reviewer_id == reviewer_id,
                Assignment.review_unit_id.in_(campaign_unit_ids),
                Assignment.status.in_({"submitted", "revision_requested"}),
            )
            .limit(1)
        )
        or session.scalar(
            select(ReviewItemAnswer.id)
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                ReviewItemAnswer.assignment_id.in_(reviewer_assignment_ids),
            )
            .limit(1)
        )
        or session.scalar(
            select(AnnotationRevision.id)
            .where(
                AnnotationRevision.tenant_id == tenant_id,
                AnnotationRevision.assignment_id.in_(reviewer_assignment_ids),
            )
            .limit(1)
        )
    )


class ReviewCampaignReviewersMixin(ReviewServiceBase):
    _MAX_SELECTED_REVIEWERS = 200

    def add_campaign_reviewer(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        request_id: str,
    ) -> CampaignReviewersResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        self._require_reviewer_manageable(campaign)
        self._require_active_reviewer(session, tenant_id, reviewer_id)
        reviewer_ids = _selected_reviewer_ids(campaign)
        if reviewer_id not in reviewer_ids:
            if len(reviewer_ids) >= self._MAX_SELECTED_REVIEWERS:
                raise APIError(
                    422,
                    "too_many_selected_reviewers",
                    "Too many selected reviewers",
                    f"A campaign may select at most {self._MAX_SELECTED_REVIEWERS} reviewers.",
                )
            reviewer_ids = [*reviewer_ids, reviewer_id]
            campaign.policy_json = {
                **campaign.policy_json,
                "selected_reviewer_ids": [str(rid) for rid in reviewer_ids],
            }
            campaign.lock_version += 1
            session.flush()
            append_audit_event(
                session,
                actor_user_id=principal.user.id,
                actor_type="user",
                event_type="admin.campaign_reviewer_added",
                object_type="campaign",
                object_id=str(campaign.id),
                request_id=request_id,
                payload={"tenant_id": str(tenant_id), "reviewer_id": str(reviewer_id)},
                key=self.audit_key,
            )
        return CampaignReviewersResponse(
            campaign_id=campaign.id, selected_reviewer_ids=reviewer_ids
        )

    def remove_campaign_reviewer(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        request_id: str,
    ) -> CampaignReviewersResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        self._require_reviewer_manageable(campaign)
        reviewer_ids = _selected_reviewer_ids(campaign)
        if reviewer_id in reviewer_ids:
            self._require_reviewer_has_no_work(
                session, tenant_id=tenant_id, campaign_id=campaign_id, reviewer_id=reviewer_id
            )
            if len(reviewer_ids) == 1 and self._campaign_has_assignments(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            ):
                raise APIError(
                    422,
                    "campaign_reviewer_minimum_required",
                    "At least one reviewer is required",
                    "A campaign with published assignments must keep at least one selected "
                    "reviewer.",
                )
            reviewer_ids = [rid for rid in reviewer_ids if rid != reviewer_id]
            campaign.policy_json = {
                **campaign.policy_json,
                "selected_reviewer_ids": [str(rid) for rid in reviewer_ids],
            }
            campaign.lock_version += 1
            session.flush()
            append_audit_event(
                session,
                actor_user_id=principal.user.id,
                actor_type="user",
                event_type="admin.campaign_reviewer_removed",
                object_type="campaign",
                object_id=str(campaign.id),
                request_id=request_id,
                payload={"tenant_id": str(tenant_id), "reviewer_id": str(reviewer_id)},
                key=self.audit_key,
            )
        return CampaignReviewersResponse(
            campaign_id=campaign.id, selected_reviewer_ids=reviewer_ids
        )

    @staticmethod
    def _require_reviewer_manageable(campaign: Campaign) -> None:
        if campaign.status not in _REVIEWER_MANAGEABLE_STATUSES:
            raise APIError(
                409,
                "campaign_reviewers_locked",
                "Campaign reviewers locked",
                "Reviewers can only be added or removed while the campaign is active.",
            )

    @staticmethod
    def _campaign_has_assignments(
        session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> bool:
        return (
            session.scalar(
                select(Assignment.id)
                .join(
                    ReviewUnit,
                    (ReviewUnit.tenant_id == Assignment.tenant_id)
                    & (ReviewUnit.id == Assignment.review_unit_id),
                )
                .where(
                    Assignment.tenant_id == tenant_id,
                    ReviewUnit.campaign_id == campaign_id,
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _require_reviewer_has_no_work(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        reviewer_id: uuid.UUID,
    ) -> None:
        if campaign_reviewer_work_exists(
            session, tenant_id=tenant_id, campaign_id=campaign_id, reviewer_id=reviewer_id
        ):
            raise APIError(
                422,
                "campaign_reviewer_work_exists",
                "Reviewer has work in this campaign",
                "This reviewer has saved or submitted review work and cannot be removed from the "
                "campaign. Keep the reviewer selected or close the campaign.",
            )

    @staticmethod
    def _require_active_reviewer(
        session: Session, tenant_id: uuid.UUID, reviewer_id: uuid.UUID
    ) -> None:
        row = session.execute(
            select(User.status, TenantMembership.status)
            .select_from(TenantMembership)
            .join(User, User.id == TenantMembership.user_id)
            .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == reviewer_id,
                RoleGrant.role_code == "reviewer",
                RoleGrant.revoked_at.is_(None),
            )
        ).first()
        if row is None:
            raise APIError(
                404,
                "reviewer_not_found",
                "Reviewer not found",
                "The reviewer is not on this tenant's roster.",
            )
        user_status, membership_status = row
        if user_status != "active" or membership_status != "active":
            raise APIError(
                409,
                "reviewer_not_eligible",
                "Reviewer not eligible",
                "The reviewer is not active in this tenant.",
            )
