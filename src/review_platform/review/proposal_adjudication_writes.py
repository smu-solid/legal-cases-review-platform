"""Reviewer-added adjudication mutations, private to the acting adjudicator."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.adjudication_decisions import ReviewAdjudicationDecisionMixin
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.models import AdjudicationParticipation
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.proposal_adjudication_guards import locked_participation
from review_platform.review.proposal_adjudication_read import ReviewProposalAdjudicationReadMixin
from review_platform.review.proposal_adjudication_store import editable_item, private_items
from review_platform.review.proposal_decision_validation import resolve_proposal_decision
from review_platform.review.proposal_membership import change_membership
from review_platform.review.schemas import (
    AdjudicationCaseWorkspace,
    AdjudicationDecisionInput,
    PseudonymousGroupedSubmission,
)
from review_platform.review.schemas.proposal_adjudication import (
    ProposalAdjudicationWorkspace,
    ProposalDecisionWrite,
    ProposalMembershipChange,
)


class ReviewProposalAdjudicationMixin(
    ReviewProposalAdjudicationReadMixin,
    ReviewAdjudicationDecisionMixin,
):
    def mutate_proposal_adjudication(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        body: ProposalMembershipChange | ProposalDecisionWrite,
        item_id: uuid.UUID | None,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None = None,
    ) -> ProposalAdjudicationWorkspace:
        # This authorized read acquires the actor/case membership lock before inspecting state.
        view = self.proposal_adjudication_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        operation = f"review.proposal_adjudication.{adjudication_id}.{item_id or 'membership'}"
        digest = self._request_digest(body.model_dump(mode="json"))
        replay = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=digest,
        )
        if replay is not None:
            return ProposalAdjudicationWorkspace.model_validate(replay.response_json)
        if not view.ready:
            raise APIError(
                409,
                "proposal_reviews_pending",
                "Case reviews pending",
                "Reviewer-added items require the configured number of case submissions.",
            )
        workspace = self.adjudication_case_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        changed, event = self._apply_proposal_change(
            session,
            tenant_id,
            principal,
            body,
            item_id,
            view,
            workspace,
            idempotency_key,
            request_id,
        )
        return self._proposal_result(
            session,
            tenant_id,
            adjudication_id,
            principal,
            body,
            changed,
            event,
            operation,
            digest,
            idempotency_key,
            request_id,
            artifact_store,
        )

    def _apply_proposal_change(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: ProposalMembershipChange | ProposalDecisionWrite,
        item_id: uuid.UUID | None,
        view: ProposalAdjudicationWorkspace,
        workspace: AdjudicationCaseWorkspace,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[list[uuid.UUID], str]:
        items = private_items(
            session, tenant_id, workspace.campaign.campaign_id, workspace.case_id, principal.user.id
        )
        if isinstance(body, ProposalMembershipChange):
            changed = change_membership(
                session, workspace=workspace, actor=principal.user.id, items=items, body=body
            )
            event = "review.proposal_membership_changed"
        else:
            changed = self._write_proposal_decision(
                session,
                tenant_id,
                principal,
                body,
                item_id,
                items,
                view,
                workspace,
                idempotency_key,
                request_id,
            )
            event = (
                "review.proposal_adjudicated"
                if body.submit
                else "review.proposal_adjudication_draft"
            )
        return changed, event

    def _proposal_result(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        body: ProposalMembershipChange | ProposalDecisionWrite,
        changed: list[uuid.UUID],
        event: str,
        operation: str,
        digest: str,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None,
    ) -> ProposalAdjudicationWorkspace:
        session.flush()
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type=event,
            object_type="proposal_adjudication",
            object_id=str(adjudication_id),
            request_id=request_id,
            payload={
                "request": body.model_dump(mode="json"),
                "item_ids": [str(i) for i in changed],
            },
            key=self.audit_key,
        )
        response = self.proposal_adjudication_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=digest,
            response=response.model_dump(mode="json"),
        )
        return response

    def _write_proposal_decision(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: ProposalDecisionWrite,
        item_id: uuid.UUID | None,
        items: list[ProposalAdjudicationItem],
        view: ProposalAdjudicationWorkspace,
        workspace: AdjudicationCaseWorkspace,
        idempotency_key: str,
        request_id: str,
    ) -> list[uuid.UUID]:
        if item_id is None:
            raise APIError(422, "item_required", "Item required", "Choose an adjudication item.")
        item = editable_item(items, item_id, body.expected_version)
        projected = next(i for i in view.items if i.id == item.id)
        value, spans = resolve_proposal_decision(
            body.decision,
            projected,
            workspace,
            submit=body.submit,
            verified_snapshot_ids=set(view.source_snapshot_ids),
        )
        participation = None
        if item.extracted_adjudication_id:
            participation = locked_participation(
                session, tenant_id, principal.user.id, item.extracted_adjudication_id
            )
        if body.submit:
            if participation:
                self._submit_combined_extracted(
                    session,
                    tenant_id=tenant_id,
                    principal=principal,
                    participation=participation,
                    workspace=workspace,
                    body=body,
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                )
            item.decision_json = body.decision.model_dump(mode="json")
            item.final_value = value
            item.final_provenance_json = [s.model_dump(mode="json") for s in spans]
            item.state = "submitted"
            item.submitted_at = now_utc()
            item.draft_json = None
        else:
            item.draft_json = body.decision.model_dump(mode="json")
        item.lock_version += 1
        return [item.id]

    def _submit_combined_extracted(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        participation: AdjudicationParticipation,
        workspace: AdjudicationCaseWorkspace,
        body: ProposalDecisionWrite,
        idempotency_key: str,
        request_id: str,
    ) -> None:
        field = next(
            i
            for g in workspace.field_groups
            for i in g.items
            if i.adjudication_id == participation.adjudication_id
        )
        decision = body.decision

        def assessment(submission: PseudonymousGroupedSubmission) -> str:
            if decision.outcome == "all_equivalent_supported":
                return "correct"
            if decision.outcome in {"unsupported_or_not_locatable", "exceptional_skip"}:
                return "not_assessable"
            return (
                "correct"
                if submission.submission_id == decision.preferred_submission_id
                else "incorrect"
            )

        assessments = [
            {"submission_id": str(s.submission_id), "assessment": assessment(s)}
            for s in field.submissions
        ]
        canonical = AdjudicationDecisionInput.model_validate(
            dict(
                outcome=decision.outcome,
                preferred_proposal_id=decision.preferred_proposal_id,
                preferred_submission_id=decision.preferred_submission_id,
                corrected_value=decision.corrected_value or None,
                corrected_value_display=decision.corrected_value or None,
                comment=decision.comment or None,
                reviewer_assessments=assessments,
                evidence_ids=field.evidence_window_ids,
            )
        )
        context = self._decision_context(
            session,
            tenant_id=tenant_id,
            adjudication_id=field.adjudication_id,
            principal=principal,
            participation=participation,
        )
        final, _response = self._persist_decision(
            session,
            tenant_id=tenant_id,
            context=context,
            principal=principal,
            decision=canonical,
            assessments_json=assessments,
            idempotency_key=idempotency_key,
        )
        self._audit_adjudication_submission(
            session, context=context, principal=principal, final=final, request_id=request_id
        )
