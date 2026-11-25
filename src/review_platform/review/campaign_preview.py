"""Serialized availability previews and their API response projection."""

from __future__ import annotations

import logging
import threading
import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.review.base import ReviewServiceBase
from review_platform.review.campaign_availability import (
    CampaignAvailability,
    compute_availability,
)
from review_platform.review.campaign_case_filters import (
    VerifiedCaseFilter,
    verify_case_filter,
    verify_case_id_selection,
)
from review_platform.review.case_filter_identity import find_pool_campaign
from review_platform.review.schemas import (
    CampaignAvailabilityRequest,
    CampaignAvailabilityResponse,
    CampaignCaseFilter,
)
from review_platform.review.schemas.campaign_availability import (
    CampaignOverlapGroupCount,
    CampaignOverlapOwner,
)

logger = logging.getLogger("review_platform")

# Serialize full-pool previews within this process to bound memory and connection use.
_AVAILABILITY_PREVIEW_LOCK = threading.Lock()


_UNSEEDED_FEASIBILITIES = frozenset({"infeasible_no_cases", "infeasible_no_fields"})


def _warn_if_pool_looks_unseeded(*, tenant_id: uuid.UUID, result: CampaignAvailability) -> None:
    """Log an empty-pool hint using only the current tenant scope."""

    if result.feasibility not in _UNSEEDED_FEASIBILITIES:
        return
    if result.eligible_cases_count or result.unavailable_cases_count:
        # The pool has *some* data for this tenant -- just not matching the requested scope. Not
        # the "wrong tenant entirely" case this warning is for.
        return
    logger.warning(
        "campaign_availability.pool_looks_unseeded tenant_id=%s: the eligible-case pool is empty "
        "for this tenant. Confirm that the configured dataset has been imported into this tenant.",
        tenant_id,
    )


def _availability_response(
    result: CampaignAvailability,
    *,
    verified_filter: VerifiedCaseFilter | None = None,
) -> CampaignAvailabilityResponse:
    source_count = (
        verified_filter.source_pool_cases_count
        if verified_filter is not None
        else result.eligible_cases_count + result.unavailable_cases_count
    )
    matching_count = (
        verified_filter.case_filter_matching_count if verified_filter is not None else source_count
    )
    projected = (
        result.eligible_cases_count
        if result.requested_case_count is None
        else min(result.requested_case_count, result.eligible_cases_count)
    )
    return CampaignAvailabilityResponse(
        requested_case_count=result.requested_case_count,
        requested_field_scope=result.requested_field_scope,
        eligible_cases_count=result.eligible_cases_count,
        source_pool_cases_count=source_count,
        case_filter_matching_count=matching_count,
        case_filter_excluded_count=max(0, source_count - matching_count),
        projected_campaign_cases_count=projected,
        eligible_review_units_count=result.eligible_review_units_count,
        unavailable_cases_count=result.unavailable_cases_count,
        unavailable_review_units_count=result.unavailable_review_units_count,
        fields_fully_exhausted=result.fields_fully_exhausted,
        fields_partially_available=result.fields_partially_available,
        cases_available_for_all_selected_fields=result.cases_available_for_all_selected_fields,
        cases_available_for_some_selected_fields_only=(
            result.cases_available_for_some_selected_fields_only
        ),
        feasibility=result.feasibility,
        infeasible_message=result.infeasible_message,
        unidentifiable_pool_units_count=(
            verified_filter.unidentifiable_pool_units_count if verified_filter is not None else 0
        ),
        identity_unavailable_cases_count=(
            verified_filter.identity_unavailable_cases_count if verified_filter is not None else 0
        ),
        identity_conflict_cases_count=(
            verified_filter.identity_conflict_cases_count if verified_filter is not None else 0
        ),
        catalog_result_digest=(
            verified_filter.catalog_result_digest if verified_filter is not None else "no_catalog"
        ),
        overlap_cases_count=result.overlap_cases_count,
        overlap_group_counts=[
            CampaignOverlapGroupCount(group_id=group_id, cases_count=count)
            for group_id, count in result.overlap_group_counts
        ],
        overlap_campaigns=[
            CampaignOverlapOwner(
                campaign_id=item.campaign_id,
                campaign_key=item.campaign_key,
                campaign_name=item.campaign_name,
                cases_count=item.cases_count,
                group_counts=[
                    CampaignOverlapGroupCount(group_id=group_id, cases_count=count)
                    for group_id, count in item.group_counts
                ],
            )
            for item in result.overlap_campaigns
        ],
    )


class ReviewCampaignPreviewMixin(ReviewServiceBase):
    def preview_campaign_availability(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CampaignAvailabilityRequest,
    ) -> CampaignAvailabilityResponse:
        """Read-only availability preview against the pool -- no campaign created or mutated."""

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        pool_campaign = find_pool_campaign(session, tenant_id=tenant_id)
        if pool_campaign is None:
            empty = CampaignAvailability(
                requested_case_count=None
                if body.requested_case_count == "all"
                else body.requested_case_count,
                requested_field_scope=sorted(set(body.group_ids)),
                eligible_cases_count=0,
                eligible_review_units_count=0,
                unavailable_cases_count=0,
                unavailable_review_units_count=0,
                fields_fully_exhausted=sorted(set(body.group_ids)),
                fields_partially_available=[],
                cases_available_for_all_selected_fields=0,
                cases_available_for_some_selected_fields_only=0,
                feasibility="infeasible_no_cases",
                infeasible_message="No eligible cases are available in the pool.",
            )
            _warn_if_pool_looks_unseeded(tenant_id=tenant_id, result=empty)
            return _availability_response(empty)
        normalized_filter = body.case_filter or CampaignCaseFilter()
        verified_filter = None
        if body.case_id_selection is not None:
            if body.applied_case_id_token is None:
                raise APIError(
                    409,
                    "case_ids_not_applied",
                    "Upload case IDs first",
                    "Upload and check the case-ID file before checking availability.",
                )
            verified_filter = verify_case_id_selection(
                session,
                tenant_id=tenant_id,
                source_families=body.source_families,
                case_id_selection=body.case_id_selection,
                applied_case_id_token=body.applied_case_id_token,
                receipt_key=self.campaign_filter_receipt_key,
            )
        elif body.applied_filter_token is not None:
            verified_filter = verify_case_filter(
                session,
                tenant_id=tenant_id,
                source_families=body.source_families,
                case_filter=normalized_filter,
                applied_filter_token=body.applied_filter_token,
                database=self.campaign_filter_database,
                receipt_key=self.campaign_filter_receipt_key,
            )
        elif normalized_filter.all:
            raise APIError(
                409,
                "case_filter_not_applied",
                "Apply filters first",
                "Apply the case filter before checking availability.",
            )
        with _AVAILABILITY_PREVIEW_LOCK:
            result = compute_availability(
                session,
                tenant_id=tenant_id,
                pool_campaign_id=pool_campaign.id,
                source_families=body.source_families,
                group_ids=body.group_ids,
                requested_case_count=body.requested_case_count,
                synthesize_missing=body.synthesize_missing_values,
                allowed_case_keys=(
                    verified_filter.allowed_case_keys if verified_filter is not None else None
                ),
            )
        _warn_if_pool_looks_unseeded(tenant_id=tenant_id, result=result)
        return _availability_response(result, verified_filter=verified_filter)
