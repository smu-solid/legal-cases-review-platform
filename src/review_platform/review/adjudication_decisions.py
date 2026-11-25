"""Immutable final-decision writes for legacy and grouped adjudication flows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.adjudication_decision_validation import (
    adjudication_request_payload,
    validate_decision_metadata,
    validate_grouped_assessments,
)
from review_platform.review.adjudication_provenance import (
    validate_adjudication_correction,
)
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    Adjudication,
    AdjudicationDecision,
    AdjudicationDraft,
    AdjudicationParticipation,
    Assignment,
    Candidate,
    EvidenceWindow,
    ReviewItemAnswer,
    ReviewUnit,
)
from review_platform.review.projections import adjudication_decision_response
from review_platform.review.proposal_adjudication_guards import require_current_membership
from review_platform.review.schemas import (
    AdjudicationDecisionInput,
    AdjudicationDecisionResponse,
    AnnotationInput,
)
from review_platform.review.state_machine import validate_annotation


@dataclass(frozen=True)
class DecisionContext:
    adjudication: Adjudication
    participation: AdjudicationParticipation
    unit: ReviewUnit
    candidates: list[Candidate]
    evidence_ids: set[uuid.UUID]


class ReviewAdjudicationDecisionMixin(ReviewServiceBase):
    def _audit_adjudication_submission(
        self,
        session: Session,
        *,
        context: DecisionContext,
        principal: Principal,
        final: AdjudicationDecision,
        request_id: str,
    ) -> None:
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type=(
                "review.adjudication_resolved"
                if context.adjudication.status == "resolved"
                else "review.adjudication_participant_submitted"
            ),
            object_type="adjudication",
            object_id=str(context.adjudication.id),
            request_id=request_id,
            payload={
                "review_unit_id": str(context.adjudication.review_unit_id),
                "decision_id": str(final.id),
                "participant_id": str(context.participation.id),
                "adjudicator_id": str(principal.user.id),
                "outcome": final.outcome,
                "shared_status": context.adjudication.status,
            },
            key=self.audit_key,
        )

    def _decision_context(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        participation: AdjudicationParticipation,
    ) -> DecisionContext:
        if participation.status != "pending":
            raise APIError(
                409,
                "adjudication_not_editable",
                "Adjudication not editable",
                "This adjudicator has already submitted a final decision.",
            )
        adjudication = session.scalar(
            select(Adjudication)
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == adjudication_id,
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
        unit = session.scalar(
            select(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == adjudication.review_unit_id,
            )
            .with_for_update()
        )
        if unit is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        candidates = list(
            session.scalars(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.review_unit_id == unit.id,
                )
            )
        )
        evidence_ids = set(
            session.scalars(
                select(EvidenceWindow.id).where(
                    EvidenceWindow.tenant_id == tenant_id,
                    EvidenceWindow.review_unit_id == unit.id,
                )
            )
        )
        return DecisionContext(adjudication, participation, unit, candidates, evidence_ids)

    @staticmethod
    def _latest_grouped_submission_ids(
        session: Session, *, tenant_id: uuid.UUID, unit_id: uuid.UUID
    ) -> set[uuid.UUID]:
        latest = (
            select(
                ReviewItemAnswer.assignment_id,
                func.max(ReviewItemAnswer.revision_no).label("revision_no"),
            )
            .join(
                Assignment,
                (Assignment.tenant_id == ReviewItemAnswer.tenant_id)
                & (Assignment.id == ReviewItemAnswer.assignment_id),
            )
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                Assignment.review_unit_id == unit_id,
                Assignment.status == "submitted",
                ReviewItemAnswer.state == "submitted",
            )
            .group_by(ReviewItemAnswer.assignment_id)
            .subquery()
        )
        return set(
            session.scalars(
                select(ReviewItemAnswer.id)
                .join(
                    latest,
                    (latest.c.assignment_id == ReviewItemAnswer.assignment_id)
                    & (latest.c.revision_no == ReviewItemAnswer.revision_no),
                )
                .where(
                    ReviewItemAnswer.tenant_id == tenant_id,
                    ReviewItemAnswer.state == "submitted",
                )
            )
        )

    def _serialized_assessments(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        context: DecisionContext,
        decision: AdjudicationDecisionInput,
    ) -> list[dict[str, str]]:
        if decision.reviewer_assessments:
            submission_ids = self._latest_grouped_submission_ids(
                session, tenant_id=tenant_id, unit_id=context.unit.id
            )
            validate_grouped_assessments(
                decision,
                expected_submission_ids=submission_ids,
                required_reviews=context.unit.required_reviews,
            )
            validate_decision_metadata(decision, allowed_evidence_ids=context.evidence_ids)
            return [item.model_dump(mode="json") for item in decision.reviewer_assessments]
        validate_annotation(
            cast(AnnotationInput, decision),
            candidates_by_id={candidate.id: candidate.label for candidate in context.candidates},
            allowed_evidence_ids=context.evidence_ids,
        )
        return [item.model_dump(mode="json") for item in decision.assessments]

    def _persist_decision(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        context: DecisionContext,
        principal: Principal,
        decision: AdjudicationDecisionInput,
        assessments_json: list[dict[str, str]],
        idempotency_key: str,
    ) -> tuple[AdjudicationDecision, AdjudicationDecisionResponse]:
        final = AdjudicationDecision(
            tenant_id=tenant_id,
            adjudication_id=context.adjudication.id,
            outcome=decision.outcome,
            preferred_proposal_id=decision.preferred_proposal_id,
            corrected_value_json=decision.corrected_value,
            corrected_value_display=decision.corrected_value_display,
            comment=decision.comment,
            assessments_json=assessments_json,
            evidence_ids_json=[str(item) for item in decision.evidence_ids],
            corrected_provenance_spans_json=[
                span.model_dump(mode="json") for span in decision.corrected_provenance_spans
            ],
            client_request_id=self._key_digest(idempotency_key),
            decided_by=principal.user.id,
            decided_at=now_utc(),
        )
        session.add(final)
        session.execute(
            delete(AdjudicationDraft).where(
                AdjudicationDraft.tenant_id == tenant_id,
                AdjudicationDraft.adjudication_id == context.adjudication.id,
                AdjudicationDraft.saved_by == principal.user.id,
            )
        )
        context.participation.status = "submitted"
        context.participation.submitted_at = final.decided_at
        session.flush()
        resolved = self._resolve_shared_adjudication_if_complete(
            session,
            tenant_id=tenant_id,
            adjudication_id=context.adjudication.id,
        )
        session.flush()
        response = adjudication_decision_response(
            final,
            review_unit_id=context.adjudication.review_unit_id,
            resolved=resolved,
        )
        return final, response

    def submit_adjudication(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        decision: AdjudicationDecisionInput,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None = None,
    ) -> AdjudicationDecisionResponse:
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
        operation = f"review.adjudication.submit.{adjudication_id}"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = AdjudicationDecisionResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})
        require_current_membership(
            session, participation, decision.membership_version, decision.preferred_proposal_id
        )
        context = self._decision_context(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            participation=participation,
        )
        validate_adjudication_correction(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            adjudicator_id=principal.user.id,
            review_unit_id=context.unit.id,
            decision=decision,
            artifact_store=artifact_store,
        )
        assessments = self._serialized_assessments(
            session, tenant_id=tenant_id, context=context, decision=decision
        )
        final, response = self._persist_decision(
            session,
            tenant_id=tenant_id,
            context=context,
            principal=principal,
            decision=decision,
            assessments_json=assessments,
            idempotency_key=idempotency_key,
        )
        self._audit_adjudication_submission(
            session,
            context=context,
            principal=principal,
            final=final,
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
