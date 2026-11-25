"""Read-only allocation run views: listing, detail, matrix, workloads, and coverage."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.pagination import decode_cursor, encode_cursor
from review_platform.review.allocation.projections import run_response
from review_platform.review.allocation.schemas import (
    AllocationMatrixResponse,
    AllocationRunPage,
    AllocationRunResponse,
    ReviewerWorkloadOut,
    ReviewerWorkloadsResponse,
    SubjectCoverageOut,
    SubjectCoverageResponse,
)
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.models import AllocationRun, AllocationRunSubject


class AllocationQueryMixin(AllocationServiceBase):
    def list_runs(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        limit: int,
        cursor: str | None,
    ) -> AllocationRunPage:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        statement = (
            select(AllocationRun)
            .where(
                AllocationRun.tenant_id == tenant_id,
                AllocationRun.campaign_id == campaign_id,
            )
            .order_by(AllocationRun.created_at.desc(), AllocationRun.id)
            .limit(limit + 1)
        )
        after = decode_cursor(cursor)
        if after is not None:
            created_at, run_id = _run_keyset(after)
            statement = statement.where(
                or_(
                    AllocationRun.created_at < created_at,
                    and_(AllocationRun.created_at == created_at, AllocationRun.id > run_id),
                )
            )
        rows = session.scalars(statement).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor: str | None = None
        if has_more:
            last = page[-1]
            next_cursor = encode_cursor(
                {"created_at": last.created_at.isoformat(), "id": str(last.id)}
            )
        return AllocationRunPage(
            items=[run_response(run, None) for run in page],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
    ) -> AllocationRunResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        run = self._load_run(session, tenant_id=tenant_id, campaign_id=campaign_id, run_id=run_id)
        return run_response(run, None)

    def matrix(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
        request_id: str,
    ) -> AllocationMatrixResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        run = self._load_run(session, tenant_id=tenant_id, campaign_id=campaign_id, run_id=run_id)
        summary = run.summary_json
        coverage = summary.get("subject_coverage") or {}
        matrix = summary.get("pairwise_overlap_matrix", {})
        all_reviewer_overlap = session.scalar(
            select(func.count())
            .select_from(AllocationRunSubject)
            .where(
                AllocationRunSubject.tenant_id == tenant_id,
                AllocationRunSubject.allocation_run_id == run_id,
                AllocationRunSubject.selection_layer == "global_hub",
            )
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.matrix_viewed",
            object_type="allocation_run",
            object_id=str(run_id),
            request_id=request_id,
            payload={"campaign_id": str(campaign_id)},
            key=self.audit_key,
        )
        return AllocationMatrixResponse(
            run_id=run_id,
            pairwise_overlap_matrix=matrix,
            all_reviewer_overlap_count=int(all_reviewer_overlap or 0),
            hub_subject_count=int(coverage.get("hub_subject_count", 0)),
        )

    def reviewer_workloads(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
    ) -> ReviewerWorkloadsResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        run = self._load_run(session, tenant_id=tenant_id, campaign_id=campaign_id, run_id=run_id)
        workloads = [
            ReviewerWorkloadOut.model_validate(item)
            for item in run.summary_json.get("reviewer_workloads", [])
        ]
        return ReviewerWorkloadsResponse(run_id=run_id, reviewer_workloads=workloads)

    def subject_coverage(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
    ) -> SubjectCoverageResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        run = self._load_run(session, tenant_id=tenant_id, campaign_id=campaign_id, run_id=run_id)
        coverage = run.summary_json.get("subject_coverage")
        if coverage is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return SubjectCoverageResponse(
            run_id=run_id, subject_coverage=SubjectCoverageOut.model_validate(coverage)
        )


def _run_keyset(after: dict[str, object]) -> tuple[datetime, uuid.UUID]:
    try:
        created_at = datetime.fromisoformat(str(after["created_at"]))
        run_id = uuid.UUID(str(after["id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.") from exc
    return created_at, run_id
