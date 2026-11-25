"""Campaign closure, completion markers, and allocation summaries."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.base import ReviewServiceBase
from review_platform.review.campaign_allocation_math import (
    build_allocation_plan,
    campaign_allocation_seed,
    compute_estimated_assignments_per_reviewer,
    compute_total_assignments,
    infeasibility_reason,
)
from review_platform.review.campaign_queries import (
    CAMPAIGN_MARKED_COMPLETED_EVENT,
    _campaign_cases,
    _campaign_completed,
    _campaign_detail_response,
    _load_campaign,
    _load_campaign_for_update,
    _minimum_reviews_per_case,
    _selected_reviewer_ids,
)
from review_platform.review.case_pool import (
    POOL_CAMPAIGN_KEY,
    campaign_has_started_work,
    return_units_to_pool,
)
from review_platform.review.models import ReviewUnit
from review_platform.review.schemas import (
    CampaignAllocationPlanItem,
    CampaignAllocationSummaryResponse,
    CampaignDeleteResponse,
    CampaignDetailResponse,
)


class ReviewCampaignClosureMixin(ReviewServiceBase):
    def delete_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        confirm: bool,
        request_id: str,
    ) -> CampaignDeleteResponse:
        """Close a campaign and release its original units only before review work starts."""

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        if not confirm:
            raise APIError(
                400,
                "campaign_delete_requires_confirmation",
                "Confirmation required",
                "Deleting a campaign requires confirm=true.",
            )
        if campaign.status == "closed":
            return CampaignDeleteResponse(
                campaign_id=campaign.id, status="closed", already_closed=True
            )
        if campaign.status == "pool" or campaign.key == POOL_CAMPAIGN_KEY:
            raise APIError(
                422,
                "campaign_delete_pool_blocked",
                "Campaign delete blocked",
                "The shared case pool is not a campaign and cannot be deleted.",
            )
        if campaign.status not in {"draft", "planned", "published"}:
            raise APIError(
                422,
                "campaign_delete_invalid_status",
                "Campaign delete blocked",
                f"A campaign in '{campaign.status}' status cannot be deleted.",
            )
        if campaign_has_started_work(session, tenant_id=tenant_id, campaign_id=campaign.id):
            raise APIError(
                422,
                "campaign_delete_work_exists",
                "Campaign contains reviewer work",
                "This campaign has saved, submitted, or revision-requested reviewer work and "
                "cannot be deleted. Close or supersede it instead.",
            )
        # Return the draft's review units to the shared pool before closing, so the freed cases are
        # selectable again (the inverse of ``materialize_from_pool``).
        cases_freed, units_freed = return_units_to_pool(
            session, tenant_id=tenant_id, campaign=campaign, created_by=principal.user.id
        )
        campaign.status = "closed"
        campaign.lock_version += 1
        session.flush()
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="admin.campaign_deleted",
            object_type="campaign",
            object_id=str(campaign.id),
            request_id=request_id,
            payload={
                "tenant_id": str(tenant_id),
                "cases_returned_to_pool": cases_freed,
                "units_returned_to_pool": units_freed,
            },
            key=self.audit_key,
        )
        return CampaignDeleteResponse(
            campaign_id=campaign.id,
            status=campaign.status,
            cases_returned_to_pool=cases_freed,
            units_returned_to_pool=units_freed,
            already_closed=False,
        )

    def mark_campaign_completed(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        request_id: str,
    ) -> CampaignDetailResponse:
        """Manually mark a published campaign completed -- a display-only, one-way milestone.

        No new campaign status: "completed" is derived by ``_campaign_detail_response`` from the
        presence of a ``CAMPAIGN_MARKED_COMPLETED_EVENT`` audit event for this campaign. Idempotent
        -- a second call finds the existing event and appends nothing further. There is no
        "un-mark" endpoint.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        if campaign.status != "published":
            raise APIError(
                409,
                "campaign_not_completable",
                "Campaign not completable",
                "Only a published campaign can be marked completed.",
            )
        if not _campaign_completed(session, campaign.id):
            append_audit_event(
                session,
                actor_user_id=principal.user.id,
                actor_type="user",
                event_type=CAMPAIGN_MARKED_COMPLETED_EVENT,
                object_type="campaign",
                object_id=str(campaign.id),
                request_id=request_id,
                payload={"tenant_id": str(tenant_id)},
                key=self.audit_key,
            )
        return _campaign_detail_response(session, campaign)

    def campaign_allocation_summary(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        include_plan: bool = True,
    ) -> CampaignAllocationSummaryResponse:
        """Simple ``cases * minimum_reviews_per_case`` math plus a read-only, seeded preview plan.

        Never persists an assignment -- publishing still goes through the existing allocation-run
        preview/persist/publish endpoints.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign(session, tenant_id, campaign_id)
        minimum_reviews_per_case = _minimum_reviews_per_case(campaign)
        reviewer_ids = _selected_reviewer_ids(campaign)
        cases = _campaign_cases(session, tenant_id=tenant_id, campaign_id=campaign_id)
        selected_cases = len(cases)
        selected_reviewers = len(reviewer_ids)
        total_assignments = compute_total_assignments(selected_cases, minimum_reviews_per_case)
        estimated_per_reviewer = compute_estimated_assignments_per_reviewer(
            total_assignments, selected_reviewers
        )
        # The same plan measured in review units. Allocation is case-native, so publishing fans
        # each planned (case, reviewer) pair out over every in-scope unit of that case -- which is
        # why the publish result reports a much larger number than ``total_assignments``. Reporting
        # both stops the panel and the publish result reading as two different campaigns.
        review_units = (
            session.scalar(
                select(func.count())
                .select_from(ReviewUnit)
                .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign_id)
            )
            or 0
        )
        total_unit_assignments = compute_total_assignments(review_units, minimum_reviews_per_case)
        reason = infeasibility_reason(
            selected_cases=selected_cases,
            selected_reviewers=selected_reviewers,
            minimum_reviews_per_case=minimum_reviews_per_case,
        )
        plan = (
            []
            if reason is not None or not include_plan
            else build_allocation_plan(
                cases,
                reviewer_ids,
                minimum_reviews_per_case,
                seed=campaign_allocation_seed(campaign.key),
            )
        )
        return CampaignAllocationSummaryResponse(
            campaign_id=campaign_id,
            selected_cases=selected_cases,
            reviews_per_case=minimum_reviews_per_case,
            selected_reviewers=selected_reviewers,
            total_assignments=total_assignments,
            review_units=review_units,
            total_unit_assignments=total_unit_assignments,
            estimated_assignments_per_reviewer=estimated_per_reviewer,
            feasible=reason is None,
            infeasible_reason=reason[0] if reason else None,
            infeasible_message=reason[1] if reason else None,
            assignment_plan=[
                CampaignAllocationPlanItem(
                    review_subject_id=entry.case.review_subject_id,
                    display_title=entry.case.display_title,
                    reviewer_ids=entry.reviewer_ids,
                )
                for entry in plan
            ],
        )
