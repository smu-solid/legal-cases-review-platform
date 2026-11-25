"""Stable response projection shared by fresh and replayed reviewer answer writes."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from review_platform.review.models import ReviewItemAnswer
from review_platform.review.schemas import CorrectedProvenanceSpan, ReviewItemAnswerResponse


def _item_answer_response(
    revision: ReviewItemAnswer,
    *,
    review_unit_id: uuid.UUID,
    lock_version: int,
    replayed: bool = False,
) -> ReviewItemAnswerResponse:
    """Project a persisted value/provenance revision into its API response.

    Shared by a fresh write and by the idempotent already-submitted short-circuit so both return
    byte-identical shapes. ``ReviewItemAnswer`` rows are keyed by ``assignment_id`` only, so the
    owning review unit is threaded in from the assignment.
    """

    return ReviewItemAnswerResponse(
        id=revision.id,
        assignment_id=revision.assignment_id,
        review_unit_id=review_unit_id,
        revision_no=revision.revision_no,
        state=cast(Literal["draft", "submitted"], revision.state),
        value_correct=revision.value_correct,
        provenance_correct=revision.provenance_correct,
        corrected_value=revision.corrected_value_json,
        corrected_value_display=revision.corrected_value_display,
        comment=revision.comment,
        failure_reason=revision.failure_reason,
        evidence_ids=[uuid.UUID(value) for value in revision.evidence_ids_json],
        corrected_provenance_spans=[
            CorrectedProvenanceSpan.model_validate(span)
            for span in revision.corrected_provenance_spans_json
        ],
        created_at=revision.created_at,
        lock_version=lock_version,
        replayed=replayed,
    )
