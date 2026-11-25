"""Adjudication queue, conflict-free claim, and pseudonymised adjudication bundle."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review import adjudication_reads
from review_platform.review.adjudication_cases import adjudication_case_id, same_case_clause
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.schemas import (
    AdjudicationBundle,
    AdjudicationClaimResponse,
    AdjudicationSummary,
)


class ReviewAdjudicationMixin(ReviewServiceBase):
    def list_adjudications(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        request_id: str = "adjudication-queue",
    ) -> list[AdjudicationSummary]:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        self._reconcile_inactive_adjudicators(session, tenant_id=tenant_id, request_id=request_id)
        return adjudication_reads.adjudication_queue(
            session,
            tenant_id=tenant_id,
            principal=principal,
        )

    def claim_adjudication(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> AdjudicationClaimResponse:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        operation = "review.adjudication.claim"
        request_digest = self._request_digest({"tenant_id": str(tenant_id)})
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = AdjudicationClaimResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})
        anchor_row = session.execute(
            select(Adjudication, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
                & (AdjudicationParticipation.adjudication_id == Adjudication.id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Adjudication.tenant_id)
                & (ReviewUnit.id == Adjudication.review_unit_id),
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.status == "pending",
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status == "pending",
            )
            .order_by(Adjudication.created_at, Adjudication.id)
            .limit(1)
        ).first()
        if anchor_row is None:
            raise APIError(
                409,
                "no_adjudication_available",
                "No adjudication available",
                "No eligible adjudication is available.",
            )
        anchor, anchor_unit, anchor_subject = anchor_row
        case_id = adjudication_case_id(anchor_subject)
        case_rows = session.scalars(
            select(Adjudication)
            .join(
                AdjudicationParticipation,
                (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
                & (AdjudicationParticipation.adjudication_id == Adjudication.id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Adjudication.tenant_id)
                & (ReviewUnit.id == Adjudication.review_unit_id),
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.status == "pending",
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status == "pending",
                ReviewUnit.campaign_id == anchor_unit.campaign_id,
                same_case_clause(anchor_subject),
            )
            .order_by(Adjudication.created_at, Adjudication.id)
        ).all()
        claimed_at = now_utc()
        visible = list(case_rows) or [anchor]
        response = AdjudicationClaimResponse(
            adjudication_id=anchor.id,
            review_unit_id=anchor.review_unit_id,
            claimed_at=claimed_at,
            adjudication_ids=[item.id for item in visible],
            claimed_item_count=len(visible),
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.adjudication_claim_deprecated",
            object_type="adjudication",
            object_id=str(anchor.id),
            request_id=request_id,
            payload={
                "review_unit_id": str(anchor.review_unit_id),
                "case_id": case_id,
                "visible_item_count": len(visible),
                "ownership_changed": False,
            },
            key=self.audit_key,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
        )
        return response

    def adjudication_bundle(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
    ) -> AdjudicationBundle:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        return adjudication_reads.legacy_adjudication_bundle(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
        )
