"""Duplicate checks reuse reviewer case serialization and existing submission transactions."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.citation_duplicates import check_duplicates, require_no_duplicates
from review_platform.review.citation_inventory import apply_answer_overrides, citation_inventory
from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
from review_platform.review.models import Assignment, ReviewSubject, ReviewUnit
from review_platform.review.proposal_scope import lock_reviewer_case
from review_platform.review.proposal_validation import validate_proposal
from review_platform.review.schemas.proposals import ProposalInput, ProposalSpan
from review_platform.review.schemas.submissions import ReviewItemAnswerInput


def lock_citation_case(session: Session, assignment: Assignment) -> bool:
    row = session.execute(
        select(ReviewUnit, ReviewSubject)
        .join(
            ReviewSubject,
            ReviewSubject.id == ReviewUnit.review_subject_id,
        )
        .where(
            ReviewUnit.tenant_id == assignment.tenant_id, ReviewUnit.id == assignment.review_unit_id
        )
    ).one()
    unit, subject = row
    if unit.review_kind not in {"cited_case", "statute_reference"}:
        return False
    lock_reviewer_case(
        session,
        assignment.tenant_id,
        unit.campaign_id,
        str(subject.attributes_json.get("snapshot_local_case_external_id") or subject.id),
        assignment.reviewer_id,
    )
    return True


class ReviewCitationSubmissionMixin(ReviewGroupedBundleMixin):
    def check_citation_answer(
        self,
        session: Session,
        assignment: Assignment,
        principal: Principal,
        answer: ReviewItemAnswerInput,
        artifact_store: ArtifactStore | None,
    ) -> None:
        bundle = self.grouped_bundle(
            session,
            tenant_id=assignment.tenant_id,
            assignment_id=assignment.id,
            principal=principal,
            artifact_store=artifact_store,
        )
        for span in answer.corrected_provenance_spans:
            if span.source_snapshot_id and span.source_version:
                validate_proposal(
                    ProposalInput(
                        group_id="cited_cases",
                        provenance=[
                            ProposalSpan(
                                source_snapshot_id=span.source_snapshot_id,
                                source_version=span.source_version,
                                char_start=span.char_start,
                                char_end=span.char_end,
                            )
                        ],
                    ),
                    submitted=False,
                    content=bundle.source_render.content,
                    snapshot_id=bundle.source_render.source_snapshot_id,
                    verified_snapshot_ids=set(bundle.proposal_source_snapshot_ids),
                )
        apply_answer_overrides(bundle, {assignment.review_unit_id: answer})
        group_id = next(
            g.group_id
            for g in bundle.field_groups
            if any(i.review_unit_id == assignment.review_unit_id for i in g.items)
        )
        inventory = citation_inventory(bundle, group_id)
        current = next((i for i in inventory if i.id == assignment.review_unit_id), None)
        if current is None:
            return
        # A submitted 'incorrect' answer with only a note is not an accepted replacement.
        replacement = answer.corrected_value_display or (
            answer.corrected_value if isinstance(answer.corrected_value, str) else ""
        )
        others = (
            inventory
            if answer.value_correct is False and replacement.strip()
            else [i for i in inventory if i.authored]
        )
        require_no_duplicates(check_duplicates(current, others))

    def check_case_citations(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        artifact_store: ArtifactStore | None,
    ) -> None:
        bundle = self.grouped_bundle(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        for group_id in ("cited_cases", "statutes_cited"):
            inventory = citation_inventory(bundle, group_id)
            for item in inventory:
                # Preserve upstream duplicates; reject new authored/corrected conflicts only.
                if item.authored:
                    require_no_duplicates(check_duplicates(item, inventory))
