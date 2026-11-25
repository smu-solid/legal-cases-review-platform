from __future__ import annotations

import uuid

import pytest

from review_platform.common.errors import APIError
from review_platform.review.adjudication_provenance import validate_adjudication_provenance
from review_platform.review.schemas import AdjudicationDecisionInput


def decision(*, outcome: str, evidence_id: uuid.UUID) -> AdjudicationDecisionInput:
    return AdjudicationDecisionInput.model_validate(
        {
            "outcome": outcome,
            "corrected_provenance_spans": [
                {"evidence_window_id": evidence_id, "char_start": 1, "char_end": 4}
            ],
        }
    )


@pytest.mark.no_db
def test_corrected_provenance_requires_all_wrong() -> None:
    evidence_id = uuid.uuid4()
    with pytest.raises(APIError) as raised:
        validate_adjudication_provenance(
            decision(outcome="all_equivalent_supported", evidence_id=evidence_id),
            allowed_evidence_ids={evidence_id},
            source_length=10,
        )
    assert raised.value.code == "corrected_provenance_spans_invalid"


@pytest.mark.no_db
def test_corrected_provenance_requires_authorized_evidence() -> None:
    with pytest.raises(APIError) as raised:
        validate_adjudication_provenance(
            decision(outcome="all_wrong", evidence_id=uuid.uuid4()),
            allowed_evidence_ids={uuid.uuid4()},
            source_length=10,
        )
    assert raised.value.code == "corrected_provenance_spans_invalid"
