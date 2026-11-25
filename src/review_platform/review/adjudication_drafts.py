"""Mutable adjudication drafts; final decisions remain immutable and separate."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.adjudication_decision_validation import adjudication_request_payload
from review_platform.review.adjudication_provenance import (
    validate_adjudication_correction,
)
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    Adjudication,
    AdjudicationDraft,
    AdjudicationParticipation,
    Assignment,
)
from review_platform.review.proposal_adjudication_guards import require_current_membership
from review_platform.review.schemas import AdjudicationDraftInput, AdjudicationDraftResponse


def adjudication_draft_response(
    draft: AdjudicationDraft, *, replayed: bool = False
) -> AdjudicationDraftResponse:
    return AdjudicationDraftResponse(
        adjudication_id=draft.adjudication_id,
        decision=AdjudicationDraftInput.model_validate(draft.decision_json),
        saved_at=draft.updated_at,
        replayed=replayed,
    )


class ReviewAdjudicationDraftMixin(ReviewServiceBase):
    def _audit_adjudication_draft(
        self,
        session: Session,
        *,
        adjudication: Adjudication,
        principal: Principal,
        decision: AdjudicationDraftInput,
        request_id: str,
    ) -> None:
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.adjudication_draft",
            object_type="adjudication",
            object_id=str(adjudication.id),
            request_id=request_id,
            payload={
                "review_unit_id": str(adjudication.review_unit_id),
                "adjudicator_id": str(principal.user.id),
                "outcome": decision.outcome,
            },
            key=self.audit_key,
        )

    @staticmethod
    def _editable_draft_adjudication(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
    ) -> Adjudication:
        adjudication = session.scalar(
            select(Adjudication)
            .join(
                AdjudicationParticipation,
                (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
                & (AdjudicationParticipation.adjudication_id == Adjudication.id),
            )
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == adjudication_id,
                Adjudication.status == "pending",
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status == "pending",
            )
            .with_for_update()
        )
        if adjudication is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        conflict = session.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id == adjudication.review_unit_id,
                Assignment.reviewer_id == principal.user.id,
            )
        )
        if conflict:  # pragma: no cover - claim eligibility invariant
            raise APIError(
                403, "adjudication_conflict", "Forbidden", "The action is not permitted."
            )
        return adjudication

    def save_adjudication_draft(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        decision: AdjudicationDraftInput,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None = None,
    ) -> AdjudicationDraftResponse:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        participation = session.scalar(
            select(AdjudicationParticipation)
            .where(
                AdjudicationParticipation.tenant_id == tenant_id,
                AdjudicationParticipation.adjudication_id == adjudication_id,
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status != "waived",
            )
            .with_for_update()
        )
        if participation is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        request_digest = self._request_digest(
            adjudication_request_payload(adjudication_id, decision)
        )
        operation = f"review.adjudication.draft.{adjudication_id}"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = AdjudicationDraftResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})

        require_current_membership(
            session, participation, decision.membership_version, decision.preferred_proposal_id
        )
        adjudication = self._editable_draft_adjudication(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
        )
        validate_adjudication_correction(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            adjudicator_id=principal.user.id,
            review_unit_id=adjudication.review_unit_id,
            decision=decision,
            artifact_store=artifact_store,
        )
        draft = session.scalar(
            select(AdjudicationDraft)
            .where(
                AdjudicationDraft.tenant_id == tenant_id,
                AdjudicationDraft.adjudication_id == adjudication.id,
                AdjudicationDraft.saved_by == principal.user.id,
            )
            .with_for_update()
        )
        if draft is None:
            draft = AdjudicationDraft(
                tenant_id=tenant_id,
                adjudication_id=adjudication.id,
                decision_json=decision.model_dump(mode="json"),
                saved_by=principal.user.id,
            )
            session.add(draft)
        else:
            draft.decision_json = decision.model_dump(mode="json")
            draft.updated_at = now_utc()
        session.flush()
        response = adjudication_draft_response(draft)
        self._audit_adjudication_draft(
            session,
            adjudication=adjudication,
            principal=principal,
            decision=decision,
            request_id=request_id,
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
