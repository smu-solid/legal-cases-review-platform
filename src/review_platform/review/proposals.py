"""Transactional author-owned proposal writes, independent of adjudication readiness."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.errors import APIError
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.citation_duplicates import check_duplicates, require_no_duplicates
from review_platform.review.citation_inventory import (
    apply_answer_overrides,
    citation_inventory,
    proposed_item,
)
from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
from review_platform.review.models import Assignment, ReviewSubject, ReviewUnit
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_projection import proposal_response
from review_platform.review.proposal_removal import remove_proposal, removed_response
from review_platform.review.proposal_scope import PROPOSAL_GROUPS, lock_reviewer_case
from review_platform.review.proposal_validation import validate_proposal_write
from review_platform.review.schemas.citation_duplicates import CitationDuplicateCheck
from review_platform.review.schemas.grouped_bundle import ReviewerGroupingBundle
from review_platform.review.schemas.proposals import (
    ProposalDuplicateInput,
    ProposalInput,
    ReviewerProposal,
)


class ReviewProposalMixin(ReviewGroupedBundleMixin):
    def _proposal_case(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
    ) -> tuple[uuid.UUID, str]:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        row = session.execute(
            select(ReviewUnit, ReviewSubject)
            .select_from(Assignment)
            .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
                assignment_is_live(),
            )
            .with_for_update(of=Assignment)
        ).first()
        if row is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        unit, subject = row
        case_id = str(subject.attributes_json.get("snapshot_local_case_external_id") or subject.id)
        lock_reviewer_case(session, tenant_id, unit.campaign_id, case_id, principal.user.id)
        return unit.campaign_id, case_id

    def save_proposal(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        proposal_id: uuid.UUID,
        principal: Principal,
        body: ProposalInput,
        state: Literal["draft", "submitted", "removed"],
        expected_version: int,
        idempotency_key: str,
        artifact_store: ArtifactStore | None,
    ) -> ReviewerProposal:
        campaign_id, case_id = self._proposal_case(session, tenant_id, assignment_id, principal)
        bundle = self.grouped_bundle(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        proposal = self._owned_proposal(
            session,
            proposal_id,
            tenant_id,
            campaign_id,
            case_id,
            principal.user.id,
        )
        removed = removed_response(session, tenant_id, principal.user.id, proposal_id, state)
        if removed is not None:
            return removed
        operation = f"review.proposal.{proposal_id}.{state}"
        digest = self._request_digest(
            {"body": body.model_dump(mode="json"), "version": expected_version}
        )
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=digest,
        )
        if record is not None:
            return ReviewerProposal.model_validate(record.response_json)
        if proposal is not None and proposal.state == state and state in ("submitted", "removed"):
            return proposal_response(proposal)
        validate_proposal_write(bundle, proposal, body, state, expected_version)
        self._check_submission_duplicates(bundle, proposal_id, body, state)
        result = self._persist_proposal(
            session,
            proposal=proposal,
            proposal_id=proposal_id,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            case_id=case_id,
            assignment_id=assignment_id,
            reviewer_id=principal.user.id,
            body=body,
            state=state,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=digest,
            response=result.model_dump(mode="json"),
            etag=str(result.lock_version),
        )
        return result

    @staticmethod
    def _check_submission_duplicates(
        bundle: ReviewerGroupingBundle,
        proposal_id: uuid.UUID,
        body: ProposalInput,
        state: str,
    ) -> None:
        if state == "submitted" and body.group_id in PROPOSAL_GROUPS:
            require_no_duplicates(
                check_duplicates(
                    proposed_item(bundle, proposal_id, body),
                    citation_inventory(bundle, body.group_id),
                ),
            )

    def check_proposal_duplicates(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        proposal_id: uuid.UUID,
        principal: Principal,
        body: ProposalDuplicateInput,
        artifact_store: ArtifactStore | None,
    ) -> CitationDuplicateCheck:
        campaign_id, case_id = self._proposal_case(session, tenant_id, assignment_id, principal)
        self._owned_proposal(
            session, proposal_id, tenant_id, campaign_id, case_id, principal.user.id
        )
        bundle = self.grouped_bundle(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        if not any(g.group_id == body.group_id for g in bundle.field_groups):
            raise APIError(
                403, "proposal_group_ineligible", "Group unavailable", "Group not assigned."
            )
        apply_answer_overrides(bundle, body.answer_overrides)
        inventory = (
            citation_inventory(bundle, body.group_id) if body.group_id in PROPOSAL_GROUPS else []
        )
        return check_duplicates(proposed_item(bundle, proposal_id, body), inventory)

    @staticmethod
    def _owned_proposal(
        session: Session,
        proposal_id: uuid.UUID,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        case_id: str,
        reviewer_id: uuid.UUID,
    ) -> ReviewerAddedProposal | None:
        proposal = session.scalar(
            select(ReviewerAddedProposal)
            .where(
                ReviewerAddedProposal.id == proposal_id,
                ReviewerAddedProposal.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if proposal is not None and (
            proposal.reviewer_id != reviewer_id
            or proposal.campaign_id != campaign_id
            or proposal.case_id != case_id
        ):
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return proposal

    @staticmethod
    def _persist_proposal(
        session: Session,
        *,
        proposal: ReviewerAddedProposal | None,
        proposal_id: uuid.UUID,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        case_id: str,
        assignment_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        body: ProposalInput,
        state: str,
    ) -> ReviewerProposal:
        if state == "removed":
            return remove_proposal(
                session,
                proposal,
                tenant_id=tenant_id,
                reviewer_id=reviewer_id,
                proposal_id=proposal_id,
                group_id=body.group_id,
            )
        revision = {**body.model_dump(mode="json"), "state": state, "at": now_utc().isoformat()}
        if proposal is None:
            proposal = ReviewerAddedProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                case_id=case_id,
                assignment_id=assignment_id,
                reviewer_id=reviewer_id,
                group_id=body.group_id,
                value_schema=PROPOSAL_GROUPS[body.group_id][1],
                original_value=body.value,
                lock_version=1,
                revisions_json=[],
            )
            session.add(proposal)
        proposal.value = body.value
        proposal.note = body.note
        proposal.provenance_json = [p.model_dump(mode="json") for p in body.provenance]
        proposal.revisions_json = [*proposal.revisions_json, revision]
        proposal.state = state
        proposal.lock_version += 1
        if state == "submitted":
            proposal.submitted_at = now_utc()
        session.flush()
        return proposal_response(proposal)
