"""Campaign authoring and the administrative case-selection API."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.campaign_case_filters import (
    VerifiedCaseFilter,
    apply_case_filter,
    apply_case_id_selection,
    verify_case_filter,
    verify_case_id_selection,
)
from review_platform.review.campaign_pool_loading import ReviewCampaignPoolLoadingMixin
from review_platform.review.campaign_preview import ReviewCampaignPreviewMixin
from review_platform.review.case_filter_export import case_filter_export, suggest_case_subjects
from review_platform.review.models import Campaign
from review_platform.review.schemas import (
    CampaignAvailabilityResponse,
    CampaignCaseFilter,
    CampaignCaseFilterApplyRequest,
    CampaignCaseFilterApplyResponse,
    CampaignCaseFilterCorrectionRequest,
    CampaignCaseFilterCorrectionResponse,
    CampaignCaseFilterExportRequest,
    CampaignCaseIdApplyRequest,
    CampaignCaseIdApplyResponse,
    CreateCampaignRequest,
    CreateCampaignResponse,
)

logger = logging.getLogger("review_platform")


class ReviewCampaignPoolMixin(ReviewCampaignPreviewMixin, ReviewCampaignPoolLoadingMixin):
    def apply_campaign_case_filters(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CampaignCaseFilterApplyRequest,
    ) -> CampaignCaseFilterApplyResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        return apply_case_filter(
            session,
            tenant_id=tenant_id,
            source_families=body.source_families,
            case_filter=body.case_filter,
            database=self.campaign_filter_database,
            receipt_key=self.campaign_filter_receipt_key,
        )

    def apply_campaign_case_ids(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CampaignCaseIdApplyRequest,
    ) -> CampaignCaseIdApplyResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        return apply_case_id_selection(
            session,
            tenant_id=tenant_id,
            source_families=body.source_families,
            case_id_selection=body.case_id_selection,
            receipt_key=self.campaign_filter_receipt_key,
        )

    def suggest_campaign_case_filter_corrections(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CampaignCaseFilterCorrectionRequest,
    ) -> CampaignCaseFilterCorrectionResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        suggestions = suggest_case_subjects(
            session,
            tenant_id=tenant_id,
            source_families=body.source_families,
            query=body.query,
            limit=body.limit,
            database=self.campaign_filter_database,
        )
        return CampaignCaseFilterCorrectionResponse(typed_value=body.query, suggestions=suggestions)

    def export_campaign_case_filter_ids(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CampaignCaseFilterExportRequest,
    ) -> tuple[str, str]:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        exported = case_filter_export(
            session,
            tenant_id=tenant_id,
            source_families=body.source_families,
            case_filter=body.case_filter,
            applied_filter_token=body.applied_filter_token,
            database=self.campaign_filter_database,
            receipt_key=self.campaign_filter_receipt_key,
        )
        return exported.filename, exported.content

    def create_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: CreateCampaignRequest,
        request_id: str,
    ) -> CreateCampaignResponse:
        """Author a draft campaign, optionally materialized from the eligible case pool."""

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        source_families = list(body.review_scope.source_families if body.review_scope else [])
        normalized_filter = body.case_filter or CampaignCaseFilter()
        verified_filter: VerifiedCaseFilter | None = None
        if body.case_id_selection is not None:
            if body.applied_case_id_token is None:
                raise APIError(
                    409,
                    "case_ids_not_applied",
                    "Upload case IDs first",
                    "Upload and check the case-ID file before creating the campaign.",
                )
            verified_filter = verify_case_id_selection(
                session,
                tenant_id=tenant_id,
                source_families=source_families,
                case_id_selection=body.case_id_selection,
                applied_case_id_token=body.applied_case_id_token,
                receipt_key=self.campaign_filter_receipt_key,
            )
        elif body.applied_filter_token is not None:
            verified_filter = verify_case_filter(
                session,
                tenant_id=tenant_id,
                source_families=source_families,
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
                "Apply the case filter before creating the campaign.",
            )

        existing = session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.key == body.campaign_key
            )
        )
        if existing is not None:
            raise APIError(
                409,
                "campaign_key_exists",
                "Conflict",
                "A campaign with this key already exists in the tenant.",
            )
        scope_json = body.review_scope.model_dump(mode="json") if body.review_scope else None
        minimum_reviews_per_case = resolve_minimum_reviews_per_case(body.reviews_per_case)
        campaign = Campaign(
            tenant_id=tenant_id,
            key=body.campaign_key,
            name=body.campaign_name,
            status="draft",
            policy_version="authored-v1",
            policy_json={
                "minimum_reviews_per_case": minimum_reviews_per_case,
                "authored": True,
                "synthesize_missing_values": body.synthesize_missing_values,
                "case_filter": normalized_filter.model_dump(mode="json"),
                "case_id_selection": (
                    body.case_id_selection.model_dump(mode="json")
                    if body.case_id_selection is not None
                    else None
                ),
                "case_id_selection_file_name": body.case_id_selection_file_name,
            },
            review_scope_json=scope_json,
            manifest_digest=digest_json({"authored": body.campaign_key}),
            created_by=principal.user.id,
        )
        session.add(campaign)
        session.flush()

        availability: CampaignAvailabilityResponse | None = None
        not_ready_for_publish = False
        materialized_units = 0
        if body.requested_case_count is not None:
            availability, _cases, materialized_units, not_ready_for_publish = (
                self._materialize_from_pool(
                    session,
                    tenant_id=tenant_id,
                    created_by=principal.user.id,
                    campaign=campaign,
                    source_families=source_families,
                    group_ids=list(body.review_scope.group_ids if body.review_scope else []),
                    requested_case_count=body.requested_case_count,
                    confirm_smaller_count=body.confirm_smaller_count,
                    confirm_remaining_fields_only=body.confirm_remaining_fields_only,
                    required_reviews=minimum_reviews_per_case,
                    synthesize_missing=body.synthesize_missing_values,
                    verified_filter=verified_filter,
                )
            )
            if availability.feasibility in {"infeasible_no_cases", "infeasible_no_fields"}:
                raise APIError(
                    422,
                    "campaign_no_cases_available",
                    "No cases available",
                    availability.infeasible_message
                    or "No cases or fields are available for this campaign scope. "
                    "The campaign was not created.",
                )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="admin.campaign_created",
            object_type="campaign",
            object_id=str(campaign.id),
            request_id=request_id,
            payload={
                "tenant_id": str(tenant_id),
                "campaign_key": body.campaign_key,
                "materialized_units": materialized_units,
                "case_filter": normalized_filter.model_dump(mode="json"),
                "case_id_selection_digest": (
                    digest_json(body.case_id_selection.model_dump(mode="json"))
                    if body.case_id_selection is not None
                    else None
                ),
                "case_filter_matching_count": (
                    availability.case_filter_matching_count if availability is not None else None
                ),
            },
            key=self.audit_key,
        )
        return CreateCampaignResponse(
            campaign_id=campaign.id,
            campaign_key=campaign.key,
            campaign_name=campaign.name,
            status=campaign.status,
            total_units=materialized_units,
            review_scope=body.review_scope,
            reviews_per_case=minimum_reviews_per_case,
            availability=availability,
            not_ready_for_publish=not_ready_for_publish,
        )
