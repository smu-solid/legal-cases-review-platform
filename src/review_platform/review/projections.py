"""Pure mappers from review ORM rows to review API response schemas."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Literal, cast

from review_platform.review.models import (
    AdjudicationDecision,
    AnnotationRevision,
    Assignment,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
)
from review_platform.review.schemas import (
    AdjudicationDecisionResponse,
    AnnotationRevisionResponse,
    AssignmentLeaseResponse,
    AssignmentRevisionRequestResponse,
    AssignmentSummary,
    CandidateAssessmentInput,
    CandidateResponse,
    ClaimResponse,
    CorrectedProvenanceSpan,
    EvidenceWindowResponse,
    GroundedIn,
    ReviewerAssessmentInput,
    ReviewSubjectResponse,
)
from review_platform.review.source_safety import clamp_snippet


def assignment_claim_response(assignment: Assignment) -> ClaimResponse:
    return ClaimResponse(
        assignment_id=assignment.id,
        review_unit_id=assignment.review_unit_id,
        status=cast(Literal["claimed"], assignment.status),
        lease_expires_at=assignment.lease_expires_at,
        revision_requested_at=assignment.revision_requested_at,
        revision_reason=assignment.revision_reason,
        lock_version=assignment.lock_version,
    )


def assignment_lease_response(
    assignment: Assignment, *, replayed: bool = False
) -> AssignmentLeaseResponse:
    return AssignmentLeaseResponse(
        assignment_id=assignment.id,
        review_unit_id=assignment.review_unit_id,
        status=cast(
            Literal["claimed", "submitted", "released", "revision_requested"],
            assignment.status,
        ),
        lease_expires_at=assignment.lease_expires_at,
        revision_requested_at=assignment.revision_requested_at,
        revision_reason=assignment.revision_reason,
        lock_version=assignment.lock_version,
        replayed=replayed,
    )


def assignment_revision_response(
    assignment: Assignment, *, replayed: bool = False
) -> AssignmentRevisionRequestResponse:
    return AssignmentRevisionRequestResponse(
        assignment_id=assignment.id,
        review_unit_id=assignment.review_unit_id,
        status=cast(Literal["revision_requested"], assignment.status),
        lease_expires_at=assignment.lease_expires_at,
        revision_requested_at=assignment.revision_requested_at,
        revision_reason=assignment.revision_reason,
        lock_version=assignment.lock_version,
        replayed=replayed,
    )


def assignment_summary(assignment: Assignment) -> AssignmentSummary:
    return AssignmentSummary(
        assignment_id=assignment.id,
        review_unit_id=assignment.review_unit_id,
        status=cast(
            Literal["claimed", "submitted", "released", "revision_requested"],
            assignment.status,
        ),
        lease_expires_at=assignment.lease_expires_at,
        revision_requested_at=assignment.revision_requested_at,
        revision_reason=assignment.revision_reason,
        lock_version=assignment.lock_version,
    )


def subject_response(subject: ReviewSubject) -> ReviewSubjectResponse:
    public_attributes = {
        key: value
        for key, value in subject.attributes_json.items()
        if not key.startswith("snapshot_local_")
    }
    return ReviewSubjectResponse(
        id=subject.id,
        subject_kind=subject.subject_kind,
        external_subject_id=subject.external_subject_id,
        display_title=subject.display_title,
        display_subtitle=subject.display_subtitle,
        source_snapshot_id=subject.source_snapshot_id,
        source_version=subject.source_version,
        primary_source_ref=subject.primary_source_ref,
        attributes=public_attributes,
    )


def candidate_response(candidate: Candidate) -> CandidateResponse:
    return CandidateResponse(
        id=candidate.id,
        label=cast(Literal["A", "B"], candidate.label),
        value=candidate.value_json,
        verdict=candidate.verdict,
        rationale=candidate.rationale,
        supporting_quote=candidate.supporting_quote,
    )


def grounded_in_index(attributes: Mapping[str, Any] | None) -> dict[str, GroundedIn]:
    """``source_sha256 -> GroundedIn`` from the subject's OWN persisted observations.

    Field units carry ``member_values`` (one per family member, with the member's document
    sha and its value -- the citation itself for citation fields); relation units carry
    ``relation_sources`` (one per contributing member observation). Nothing outside
    these attributes is consulted, so the descriptor can only ever name a document
    already represented on this subject, and no internal case identifier is copied out
    of them (reviewer blindness)."""
    index: dict[str, GroundedIn] = {}
    if not attributes:
        return index
    citation_field = attributes.get("field_name") in ("citation_neutral", "cases.citation_neutral")
    for member in attributes.get("member_values") or []:
        if not isinstance(member, Mapping) or not member.get("source_sha256"):
            continue
        sha = str(member["source_sha256"])
        index.setdefault(
            sha,
            GroundedIn(
                source_sha256=sha,
                source_system=_optional_str(member.get("source_system")),
                citation=_optional_str(member.get("value")) if citation_field else None,
            ),
        )
    for source in attributes.get("relation_sources") or []:
        if not isinstance(source, Mapping) or not source.get("source_document_sha256"):
            continue
        sha = str(source["source_document_sha256"])
        index.setdefault(
            sha,
            GroundedIn(source_sha256=sha, source_system=_optional_str(source.get("source_system"))),
        )
    primary = attributes.get("source_sha256")
    if primary and str(primary) not in index:
        index[str(primary)] = GroundedIn(source_sha256=str(primary))
    return index


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def evidence_response(
    evidence: EvidenceWindow,
    subject_attributes: Mapping[str, Any] | None = None,
    *,
    effective_offsets: Mapping[uuid.UUID, tuple[int, int]] | None = None,
) -> EvidenceWindowResponse:
    grounded = grounded_in_index(subject_attributes).get(evidence.source_sha256)
    offset = effective_offsets.get(evidence.id) if effective_offsets else None
    if grounded is None and subject_attributes is not None:
        grounded = GroundedIn(source_sha256=evidence.source_sha256)
    return EvidenceWindowResponse(
        id=evidence.id,
        kind=evidence.kind,
        snippet=clamp_snippet(evidence.snippet),
        line_start=evidence.line_start,
        line_end=evidence.line_end,
        char_start=offset[0] if offset else evidence.char_start,
        char_end=offset[1] if offset else evidence.char_end,
        source_sha256=evidence.source_sha256,
        anchor_status="anchored" if offset else evidence.anchor_status,
        grounded_in=grounded,
    )


def revision_response(
    revision: AnnotationRevision, lock_version: int, *, replayed: bool = False
) -> AnnotationRevisionResponse:
    return AnnotationRevisionResponse(
        id=revision.id,
        assignment_id=revision.assignment_id,
        revision_no=revision.revision_no,
        state=cast(Literal["draft", "submitted"], revision.state),
        outcome=revision.outcome,
        corrected_value=revision.corrected_value_json,
        corrected_value_display=revision.corrected_value_display,
        comment=revision.comment,
        assessments=[
            CandidateAssessmentInput.model_validate(item) for item in revision.assessments_json
        ],
        evidence_ids=[uuid.UUID(value) for value in revision.evidence_ids_json],
        created_at=revision.created_at,
        lock_version=lock_version,
        replayed=replayed,
    )


def adjudication_decision_response(
    decision: AdjudicationDecision,
    *,
    review_unit_id: uuid.UUID,
    replayed: bool = False,
    resolved: bool = False,
) -> AdjudicationDecisionResponse:
    candidate_assessments = [
        CandidateAssessmentInput.model_validate(item)
        for item in decision.assessments_json
        if "candidate_id" in item
    ]
    reviewer_assessments = [
        ReviewerAssessmentInput.model_validate(item)
        for item in decision.assessments_json
        if "submission_id" in item
    ]
    preferred_submission_id = next(
        (
            item.submission_id
            for item in reviewer_assessments
            if decision.outcome == "reviewer_preferred" and item.assessment == "correct"
        ),
        None,
    )
    return AdjudicationDecisionResponse(
        decision_id=decision.id,
        adjudication_id=decision.adjudication_id,
        review_unit_id=review_unit_id,
        status="resolved" if resolved else "submitted",
        outcome=decision.outcome,
        corrected_value=decision.corrected_value_json,
        corrected_value_display=decision.corrected_value_display,
        comment=decision.comment,
        assessments=candidate_assessments,
        reviewer_assessments=reviewer_assessments,
        preferred_submission_id=preferred_submission_id,
        preferred_proposal_id=decision.preferred_proposal_id,
        evidence_ids=[uuid.UUID(value) for value in decision.evidence_ids_json],
        corrected_provenance_spans=[
            CorrectedProvenanceSpan.model_validate(item)
            for item in decision.corrected_provenance_spans_json
        ],
        decided_at=decision.decided_at,
        replayed=replayed,
    )
