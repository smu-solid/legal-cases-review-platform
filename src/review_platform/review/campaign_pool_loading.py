"""Campaign top-ups and their shared, locked materialization decision."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.availability_queries import load_campaign_units
from review_platform.review.base import ReviewServiceBase
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.campaign_availability import (
    CaseCountRequest,
    compute_availability,
    lock_pool_claims,
)
from review_platform.review.campaign_case_filters import (
    VerifiedCaseFilter,
    evaluate_case_filter,
    evaluate_case_id_selection,
    verify_case_filter,
    verify_case_id_selection,
)
from review_platform.review.campaign_materialization import materialize_from_pool
from review_platform.review.campaign_preview import _availability_response
from review_platform.review.campaign_queries import _load_campaign_for_update
from review_platform.review.case_pool import get_or_create_pool_campaign
from review_platform.review.models import Campaign, ReviewUnit
from review_platform.review.schemas import (
    CampaignAvailabilityResponse,
    CampaignCaseFilter,
    CampaignCaseIdSelection,
    LoadPoolCasesRequest,
    LoadPoolCasesResponse,
)


class ReviewCampaignPoolLoadingMixin(ReviewServiceBase):
    def load_pool_cases(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        body: LoadPoolCasesRequest,
        request_id: str,
    ) -> LoadPoolCasesResponse:
        """Add pool cases using the current campaign scope and saved case selection."""

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        if campaign.status == "closed":
            raise APIError(
                409,
                "campaign_not_editable",
                "Campaign not editable",
                "Closed campaigns cannot load cases.",
            )
        scope = campaign.review_scope_json or {}
        persisted_filter = CampaignCaseFilter.model_validate(
            campaign.policy_json.get("case_filter") or {}
        )
        persisted_case_ids_raw = campaign.policy_json.get("case_id_selection")
        persisted_case_ids = (
            CampaignCaseIdSelection.model_validate(persisted_case_ids_raw)
            if persisted_case_ids_raw
            else None
        )
        selected_case_ids = (
            body.case_id_selection
            if body.case_id_selection is not None
            else (None if body.case_filter is not None else persisted_case_ids)
        )
        selected_filter = (
            body.case_filter
            if body.case_filter is not None
            else (CampaignCaseFilter() if selected_case_ids is not None else persisted_filter)
        )
        verified_filter: VerifiedCaseFilter | None
        if selected_case_ids is not None:
            if body.case_id_selection is not None:
                if body.applied_case_id_token is None:
                    raise APIError(
                        409,
                        "case_ids_not_applied",
                        "Upload case IDs first",
                        "Upload and check the case-ID file before adding cases.",
                    )
                verified_filter = verify_case_id_selection(
                    session,
                    tenant_id=tenant_id,
                    source_families=list(scope.get("source_families") or []),
                    case_id_selection=selected_case_ids,
                    applied_case_id_token=body.applied_case_id_token,
                    receipt_key=self.campaign_filter_receipt_key,
                )
            else:
                verified_filter = evaluate_case_id_selection(
                    session,
                    tenant_id=tenant_id,
                    source_families=list(scope.get("source_families") or []),
                    case_id_selection=selected_case_ids,
                )
        elif body.applied_filter_token is not None:
            verified_filter = verify_case_filter(
                session,
                tenant_id=tenant_id,
                source_families=list(scope.get("source_families") or []),
                case_filter=selected_filter,
                applied_filter_token=body.applied_filter_token,
                database=self.campaign_filter_database,
                receipt_key=self.campaign_filter_receipt_key,
            )
        elif body.case_filter is not None and selected_filter.all:
            raise APIError(
                409,
                "case_filter_not_applied",
                "Apply filters first",
                "Apply the case filter before adding cases.",
            )
        else:
            verified_filter = (
                evaluate_case_filter(
                    session,
                    tenant_id=tenant_id,
                    source_families=list(scope.get("source_families") or []),
                    case_filter=selected_filter,
                    database=self.campaign_filter_database,
                )
                if selected_filter.all
                else None
            )
        availability, materialized_cases, materialized_units, not_ready = (
            self._materialize_from_pool(
                session,
                tenant_id=tenant_id,
                created_by=principal.user.id,
                campaign=campaign,
                source_families=list(scope.get("source_families") or []),
                group_ids=list(scope.get("group_ids") or []),
                requested_case_count=body.requested_case_count,
                confirm_smaller_count=body.confirm_smaller_count,
                confirm_remaining_fields_only=body.confirm_remaining_fields_only,
                required_reviews=resolve_minimum_reviews_per_case(
                    campaign.policy_json.get("minimum_reviews_per_case")
                ),
                # Reuse the campaign's own persisted decision from creation, not the top-up
                # request -- a campaign's synthesize-missing-values choice does not change mid-life.
                synthesize_missing=bool(campaign.policy_json.get("synthesize_missing_values")),
                verified_filter=verified_filter,
            )
        )
        if availability.feasibility in {"infeasible_no_cases", "infeasible_no_fields"}:
            raise APIError(
                422,
                "campaign_no_cases_available",
                "No cases available",
                availability.infeasible_message
                or "No cases or fields are available for this campaign scope.",
            )
        if materialized_units:
            campaign.lock_version += 1
        session.flush()
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="admin.campaign_pool_cases_loaded",
            object_type="campaign",
            object_id=str(campaign.id),
            request_id=request_id,
            payload={
                "materialized_units": materialized_units,
                "case_filter": selected_filter.model_dump(mode="json"),
                "case_id_selection_digest": (
                    digest_json(selected_case_ids.model_dump(mode="json"))
                    if selected_case_ids is not None
                    else None
                ),
            },
            key=self.audit_key,
        )
        total_units = session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id)
        )
        return LoadPoolCasesResponse(
            campaign_id=campaign.id,
            availability=availability,
            materialized_cases=materialized_cases,
            materialized_units=materialized_units,
            total_units=total_units or 0,
            not_ready_for_publish=not_ready,
        )

    def _materialize_from_pool(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        created_by: uuid.UUID,
        campaign: Campaign,
        source_families: list[str],
        group_ids: list[str],
        requested_case_count: CaseCountRequest,
        confirm_smaller_count: bool,
        confirm_remaining_fields_only: bool,
        required_reviews: int,
        synthesize_missing: bool = False,
        verified_filter: VerifiedCaseFilter | None = None,
    ) -> tuple[CampaignAvailabilityResponse, int, int, bool]:
        """Compute availability against the pool and, if (confirmed) feasible, reassign units.

        Returns ``(availability, cases_moved, units_moved, not_ready_for_publish)``. Shared by
        ``create_campaign`` and ``load_pool_cases`` (top-up on an existing draft) so both paths
        apply one feasibility/confirmation policy.
        """

        pool_campaign = get_or_create_pool_campaign(
            session, tenant_id=tenant_id, created_by=created_by
        )
        lock_pool_claims(session, tenant_id=tenant_id)
        pool_rows = load_campaign_units(session, tenant_id=tenant_id, campaign_id=pool_campaign.id)
        result = compute_availability(
            session,
            tenant_id=tenant_id,
            pool_campaign_id=pool_campaign.id,
            source_families=source_families,
            group_ids=group_ids,
            requested_case_count=requested_case_count,
            synthesize_missing=synthesize_missing,
            allowed_case_keys=(
                verified_filter.allowed_case_keys if verified_filter is not None else None
            ),
            target_campaign_id=campaign.id,
            pool_rows=pool_rows,
        )
        availability = _availability_response(result, verified_filter=verified_filter)
        allow_partial_fields = (
            not synthesize_missing
            and result.feasibility == "feasible_with_remaining_fields_only"
            and confirm_remaining_fields_only
        )
        confirmed = (
            result.feasibility == "feasible_exact"
            or (result.feasibility == "feasible_with_smaller_count" and confirm_smaller_count)
            or allow_partial_fields
        )
        if not confirmed:
            return availability, 0, 0, True
        effective_group_ids = group_ids
        if allow_partial_fields:
            # Drop the fields no case can supply so the draft never declares a scope it cannot fill,
            # then materialize every case that has any of the remaining requested fields (the
            # partial coverage the admin explicitly confirmed) instead of the all-or-nothing set.
            exhausted = set(result.fields_fully_exhausted)
            effective_group_ids = [g for g in group_ids if g not in exhausted]
            if campaign.review_scope_json is not None:
                narrowed_scope = dict(campaign.review_scope_json)
                narrowed_scope["group_ids"] = effective_group_ids
                campaign.review_scope_json = narrowed_scope
        cases_moved, units_moved = materialize_from_pool(
            session,
            tenant_id=tenant_id,
            pool_campaign=pool_campaign,
            target_campaign=campaign,
            source_families=source_families,
            group_ids=effective_group_ids,
            case_count=requested_case_count,
            synthesize_missing=synthesize_missing,
            required_reviews=required_reviews,
            allow_partial_fields=allow_partial_fields,
            allowed_case_keys=(
                verified_filter.allowed_case_keys if verified_filter is not None else None
            ),
            pool_rows=pool_rows,
        )
        return availability, cases_moved, units_moved, False
