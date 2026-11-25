"""Review annotation invariants independent of transport and persistence."""

from __future__ import annotations

import uuid

from review_platform.common.errors import APIError
from review_platform.review.schemas import AnnotationInput, ReviewItemAnswerInput

COMMENT_REQUIRED_OUTCOMES = frozenset(
    {"both_wrong", "unsupported_or_not_locatable", "exceptional_skip"}
)


def validate_revision_request(status: str, reason: str, *, expected_version_matches: bool) -> str:
    """Validate a manager-requested correction window for a submitted assignment."""

    if not expected_version_matches:
        raise APIError(
            412,
            "precondition_failed",
            "Precondition failed",
            "The assignment version is stale.",
        )
    if status != "submitted":
        raise APIError(
            409,
            "assignment_revision_not_requestable",
            "Revision not requestable",
            "Only submitted assignments can be returned for reviewer revision.",
        )
    cleaned = reason.strip()
    if not cleaned:
        raise APIError(
            422,
            "revision_reason_required",
            "Revision reason required",
            "A nonblank correction reason is required.",
        )
    return cleaned


def validate_revision_reopen(status: str, *, expected_version_matches: bool) -> None:
    """Validate reviewer reopening of an assignment returned for correction.

    Only an assignment a manager returned for revision may be reopened. Recovery of an expired
    lease stays with the existing release/reclaim path, which cannot over-allocate a review-unit
    slot, so it is deliberately not a reopen transition here.
    """

    if not expected_version_matches:
        raise APIError(
            412,
            "precondition_failed",
            "Precondition failed",
            "The assignment version is stale.",
        )
    if status != "revision_requested":
        raise APIError(
            409,
            "assignment_revision_not_reopenable",
            "Revision not reopenable",
            "The assignment is not waiting for reviewer revision.",
        )


def _validate_evidence_references(
    evidence_ids: list[uuid.UUID], allowed_evidence_ids: set[uuid.UUID]
) -> None:
    if len(evidence_ids) != len(set(evidence_ids)):
        raise APIError(
            422,
            "evidence_references_invalid",
            "Invalid evidence references",
            "Evidence references must be unique.",
        )
    if not set(evidence_ids).issubset(allowed_evidence_ids):
        raise APIError(
            422,
            "evidence_references_invalid",
            "Invalid evidence references",
            "Evidence must belong to the assigned immutable snapshot.",
        )


def _validate_corrected_provenance_spans(
    answer: ReviewItemAnswerInput, allowed_evidence_ids: set[uuid.UUID]
) -> None:
    span_evidence_ids = [span.evidence_window_id for span in answer.corrected_provenance_spans]
    # A corrected span contradicts an accepted provenance, so it cannot coexist with
    # provenance_correct = true. The workspace hides the marking control unless the reviewer has
    # answered NO; this enforces the same rule server-side. A partial draft that has not yet
    # answered provenance stays legal (drafts may be partial), and submit separately requires an
    # explicit answer, so a span cannot survive into a submitted "provenance correct" answer.
    if span_evidence_ids and answer.provenance_correct is True:
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance spans require marking the provenance incorrect.",
        )
    if len(span_evidence_ids) != len(set(span_evidence_ids)):
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance spans must reference unique evidence windows.",
        )
    if not set(span_evidence_ids).issubset(allowed_evidence_ids):
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance spans must belong to the reviewed item.",
        )


def validate_item_answer(
    answer: ReviewItemAnswerInput,
    *,
    state: str,
    allowed_evidence_ids: set[uuid.UUID],
    extraction_state: str | None = None,
) -> None:
    """Server-authoritative rules for a value/provenance answer.

    Drafts may be partial (tri-state nulls allowed). A submit must make value and provenance
    correctness explicit, and an incorrect value must carry a correction or explanation so the
    decision is auditable."""

    if extraction_state == "missing" and (
        answer.value_correct is True or answer.provenance_correct is True
    ):
        raise APIError(
            422,
            "missing_value_cannot_be_correct",
            "Missing value cannot be marked correct",
            "No value was extracted for this item, so neither its value nor its provenance can be "
            "marked correct. Enter the correct value and mark its provenance instead "
            "(value_correct=false and provenance_correct=false, with a correction and evidence).",
        )
    _validate_evidence_references(answer.evidence_ids, allowed_evidence_ids)
    _validate_corrected_provenance_spans(answer, allowed_evidence_ids)
    if state != "submitted":
        return
    if answer.value_correct is None:
        raise APIError(
            422,
            "value_correctness_required",
            "Value correctness required",
            "Whether the extracted value is correct must be answered before submitting.",
        )
    if answer.provenance_correct is None:
        raise APIError(
            422,
            "provenance_correctness_required",
            "Provenance correctness required",
            "Whether the provenance is correct must be answered before submitting.",
        )
    if answer.value_correct is False:
        has_correction = (
            answer.corrected_value is not None
            or bool(answer.corrected_value_display and answer.corrected_value_display.strip())
            or bool(answer.comment and answer.comment.strip())
        )
        if not has_correction:
            raise APIError(
                422,
                "correction_or_comment_required",
                "Correction or comment required",
                "An incorrect value needs a corrected value or a nonblank comment.",
            )


def validate_annotation(
    annotation: AnnotationInput,
    *,
    candidates_by_id: dict[uuid.UUID, str],
    allowed_evidence_ids: set[uuid.UUID],
) -> None:
    assessment_by_id = {
        assessment.candidate_id: assessment.assessment for assessment in annotation.assessments
    }
    if len(assessment_by_id) != len(annotation.assessments):
        raise APIError(
            422,
            "candidate_assessments_invalid",
            "Invalid candidate assessments",
            "Each candidate must be assessed exactly once.",
        )
    if set(assessment_by_id) != set(candidates_by_id):
        raise APIError(
            422,
            "candidate_assessments_invalid",
            "Invalid candidate assessments",
            "Every visible candidate must be assessed exactly once.",
        )
    if len(annotation.evidence_ids) != len(set(annotation.evidence_ids)):
        raise APIError(
            422,
            "evidence_references_invalid",
            "Invalid evidence references",
            "Evidence references must be unique.",
        )
    if not set(annotation.evidence_ids).issubset(allowed_evidence_ids):
        raise APIError(
            422,
            "evidence_references_invalid",
            "Invalid evidence references",
            "Evidence must belong to the assigned immutable snapshot.",
        )
    comment_required = (
        annotation.outcome in COMMENT_REQUIRED_OUTCOMES
        or annotation.corrected_value is not None
        or annotation.corrected_value_display is not None
    )
    if comment_required and (annotation.comment is None or not annotation.comment.strip()):
        raise APIError(
            422,
            "comment_required",
            "Comment required",
            "A nonblank comment is required for this decision.",
        )
    by_label = {
        candidates_by_id[candidate_id]: value for candidate_id, value in assessment_by_id.items()
    }
    expected: dict[str, dict[str, str]] = {
        "candidate_a_preferred": {"A": "correct", "B": "incorrect"},
        "candidate_b_preferred": {"A": "incorrect", "B": "correct"},
        "equivalent_supported": {"A": "correct", "B": "correct"},
        "both_wrong": {"A": "incorrect", "B": "incorrect"},
    }
    required = expected.get(annotation.outcome)
    if required is not None and by_label != required:
        raise APIError(
            422,
            "candidate_assessments_inconsistent",
            "Inconsistent candidate assessments",
            "Candidate assessments do not match the selected outcome.",
        )
