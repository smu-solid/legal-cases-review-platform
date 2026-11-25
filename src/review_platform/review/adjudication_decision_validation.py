"""Pure validation for grouped adjudication decision metadata and assessments."""

from __future__ import annotations

import uuid

from review_platform.common.errors import APIError
from review_platform.review.schemas import AdjudicationDecisionInput, AdjudicationDraftInput


def adjudication_request_payload(
    adjudication_id: uuid.UUID, decision: AdjudicationDraftInput
) -> dict[str, object]:
    """Return the stable payload used by draft and final idempotency digests."""

    return {"adjudication_id": str(adjudication_id), "decision": decision.model_dump(mode="json")}


GROUPED_OUTCOMES = {
    "reviewer_assessments_recorded",
    "reviewer_preferred",
    "all_equivalent_supported",
    "all_wrong",
    "unsupported_or_not_locatable",
    "exceptional_skip",
}


def validate_decision_metadata(
    decision: AdjudicationDecisionInput, *, allowed_evidence_ids: set[uuid.UUID]
) -> None:
    evidence = decision.evidence_ids
    if len(evidence) != len(set(evidence)) or not set(evidence).issubset(allowed_evidence_ids):
        raise APIError(
            422,
            "evidence_references_invalid",
            "Invalid evidence references",
            "Evidence must be unique and belong to the assigned immutable snapshot.",
        )
    correction_supplied = (
        decision.corrected_value is not None or decision.corrected_value_display is not None
    )
    comment_required = correction_supplied or decision.outcome in {
        "all_wrong",
        "unsupported_or_not_locatable",
        "exceptional_skip",
    }
    if comment_required and (decision.comment is None or not decision.comment.strip()):
        raise APIError(
            422,
            "comment_required",
            "Comment required",
            "A nonblank comment is required for this adjudication outcome or correction.",
        )


def validate_grouped_assessments(
    decision: AdjudicationDecisionInput,
    *,
    expected_submission_ids: set[uuid.UUID],
    required_reviews: int,
) -> None:
    if decision.assessments or decision.outcome not in GROUPED_OUTCOMES:
        raise APIError(
            422,
            "reviewer_assessments_invalid",
            "Invalid reviewer assessments",
            "Grouped decisions must use a reviewer-aware adjudication outcome.",
        )
    supplied_ids = {item.submission_id for item in decision.reviewer_assessments}
    if (
        len(supplied_ids) != len(decision.reviewer_assessments)
        or supplied_ids != expected_submission_ids
        or len(expected_submission_ids) < required_reviews
    ):
        raise APIError(
            422,
            "reviewer_assessments_invalid",
            "Invalid reviewer assessments",
            "Every submitted reviewer answer must be assessed exactly once.",
        )
    assessment_by_submission = {
        item.submission_id: item.assessment for item in decision.reviewer_assessments
    }
    if decision.outcome == "reviewer_preferred":
        preferred_id = decision.preferred_submission_id
        expected = {
            submission_id: "correct" if submission_id == preferred_id else "incorrect"
            for submission_id in expected_submission_ids
        }
        consistent = (
            preferred_id in expected_submission_ids and assessment_by_submission == expected
        )
    elif decision.outcome == "all_equivalent_supported":
        consistent = decision.preferred_submission_id is None and set(
            assessment_by_submission.values()
        ) == {"correct"}
    elif decision.outcome == "all_wrong":
        consistent = decision.preferred_submission_id is None and set(
            assessment_by_submission.values()
        ) == {"incorrect"}
    elif decision.outcome in {"unsupported_or_not_locatable", "exceptional_skip"}:
        consistent = decision.preferred_submission_id is None and set(
            assessment_by_submission.values()
        ) == {"not_assessable"}
    else:
        consistent = decision.preferred_submission_id is None
    if not consistent:
        raise APIError(
            422,
            "reviewer_assessments_inconsistent",
            "Inconsistent reviewer assessments",
            "Reviewer assessments do not match the selected adjudication outcome.",
        )
