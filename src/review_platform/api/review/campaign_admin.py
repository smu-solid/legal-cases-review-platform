"""Admin review routes: synthetic import, submissions listing, and reviewer agreement metrics."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from review_platform.api.params import (
    DEFAULT_LIMIT,
    LOCK_VERSION_RESPONSE_HEADERS,
    IdempotencyKey,
    IfMatch,
    PageCursor,
    PageLimit,
    expected_version,
    set_lock_version_etag,
)
from review_platform.api.review.support import (
    ReviewContext,
)
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    AdminReviewSubmissionPage,
    AssignmentRevisionRequestInput,
    AssignmentRevisionRequestResponse,
    CampaignAvailabilityRequest,
    CampaignAvailabilityResponse,
    CampaignCaseFilterApplyRequest,
    CampaignCaseFilterApplyResponse,
    CampaignCaseFilterCorrectionRequest,
    CampaignCaseFilterCorrectionResponse,
    CampaignCaseFilterExportRequest,
    CampaignCaseIdApplyRequest,
    CampaignCaseIdApplyResponse,
    CampaignProgressResponse,
    CampaignScopeCatalogResponse,
    CreateCampaignRequest,
    CreateCampaignResponse,
    ReviewerAgreementMetricsResponse,
    ReviewerWorkloadResponse,
    SyntheticImportRequest,
    SyntheticImportResponse,
)


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    @router.post(
        "/admin/tenants/{tenant_id}/review/import-synthetic",
        response_model=SyntheticImportResponse,
        operation_id="importSyntheticReviewCampaign",
        status_code=201,
    )
    def import_synthetic(
        tenant_id: uuid.UUID,
        body: SyntheticImportRequest,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SyntheticImportResponse:
        return context.review.import_synthetic(
            session,
            tenant_id=tenant_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaigns",
        response_model=CreateCampaignResponse,
        operation_id="createCampaign",
        status_code=201,
    )
    def create_campaign(
        tenant_id: uuid.UUID,
        body: CreateCampaignRequest,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CreateCampaignResponse:
        # Author an empty draft campaign before any seed exists; a balanced real seed later imports
        # cases into it by matching campaign_key. Duplicate key is a 409 (never silent rebind).
        return context.review.create_campaign(
            session,
            tenant_id=tenant_id,
            principal=principal,
            body=body,
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaign-case-filters/apply",
        response_model=CampaignCaseFilterApplyResponse,
        operation_id="applyCampaignCaseFilters",
    )
    def apply_campaign_case_filters(
        tenant_id: uuid.UUID,
        body: CampaignCaseFilterApplyRequest,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignCaseFilterApplyResponse:
        return context.review.apply_campaign_case_filters(
            session, tenant_id=tenant_id, principal=principal, body=body
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaign-case-ids/apply",
        response_model=CampaignCaseIdApplyResponse,
        operation_id="applyCampaignCaseIds",
    )
    def apply_campaign_case_ids(
        tenant_id: uuid.UUID,
        body: CampaignCaseIdApplyRequest,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignCaseIdApplyResponse:
        return context.review.apply_campaign_case_ids(
            session, tenant_id=tenant_id, principal=principal, body=body
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaign-case-filters/corrections",
        response_model=CampaignCaseFilterCorrectionResponse,
        operation_id="suggestCampaignCaseFilterCorrections",
    )
    def suggest_campaign_case_filter_corrections(
        tenant_id: uuid.UUID,
        body: CampaignCaseFilterCorrectionRequest,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignCaseFilterCorrectionResponse:
        return context.review.suggest_campaign_case_filter_corrections(
            session, tenant_id=tenant_id, principal=principal, body=body
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaign-case-filters/export",
        response_class=Response,
        operation_id="exportCampaignCaseFilterIds",
        responses={200: {"content": {"text/plain": {}}}},
    )
    def export_campaign_case_filter_ids(
        tenant_id: uuid.UUID,
        body: CampaignCaseFilterExportRequest,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> Response:
        filename, content = context.review.export_campaign_case_filter_ids(
            session, tenant_id=tenant_id, principal=principal, body=body
        )
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaign-availability",
        response_model=CampaignAvailabilityResponse,
        operation_id="previewCampaignAvailability",
    )
    def preview_campaign_availability(
        tenant_id: uuid.UUID,
        body: CampaignAvailabilityRequest,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignAvailabilityResponse:
        # A POST (not GET) because the request body (source/field scope + requested count) can
        # exceed comfortable query-string encoding and matches the shape of loadPoolCases exactly;
        # it is still read-only -- no campaign is created or mutated.
        return context.review.preview_campaign_availability(
            session,
            tenant_id=tenant_id,
            principal=principal,
            body=body,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/assignments/{assignment_id}/request-revision",
        response_model=AssignmentRevisionRequestResponse,
        operation_id="requestAssignmentRevision",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def request_revision(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        body: AssignmentRevisionRequestInput,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        if_match: IfMatch,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AssignmentRevisionRequestResponse:
        result = context.review.request_revision(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            body=body,
            expected_version=expected_version(if_match),
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result

    @router.get(
        "/admin/tenants/{tenant_id}/review/scope-catalog",
        response_model=CampaignScopeCatalogResponse,
        operation_id="getCampaignScopeCatalog",
    )
    def campaign_scope_catalog(
        tenant_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignScopeCatalogResponse:
        return context.review.campaign_scope_catalog(
            session, tenant_id=tenant_id, principal=principal
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/submissions",
        response_model=AdminReviewSubmissionPage,
        operation_id="listAdminReviewSubmissions",
    )
    def admin_submissions(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID | None = None,
        review_unit_id: uuid.UUID | None = None,
        review_kind: Annotated[str | None, Query(max_length=60)] = None,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdminReviewSubmissionPage:
        return context.review.list_admin_submissions(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            review_unit_id=review_unit_id,
            review_kind=review_kind,
            limit=limit,
            cursor=cursor,
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/agreement-metrics",
        response_model=ReviewerAgreementMetricsResponse,
        operation_id="getReviewerAgreementMetrics",
    )
    def reviewer_agreement_metrics(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID | None = None,
        review_kind: Annotated[str | None, Query(max_length=60)] = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerAgreementMetricsResponse:
        return context.review.reviewer_agreement_metrics(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            review_kind=review_kind,
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/campaign-progress",
        response_model=CampaignProgressResponse,
        operation_id="getCampaignProgress",
    )
    def campaign_progress(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID | None = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignProgressResponse:
        return context.review.campaign_progress(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/reviewer-workload",
        response_model=ReviewerWorkloadResponse,
        operation_id="getReviewerWorkload",
    )
    def reviewer_workload(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerWorkloadResponse:
        return context.review.reviewer_workload(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
        )
