"""UTF-16 browser selections are validated against exact source content and version."""

import uuid

import pytest

from review_platform.common.errors import APIError
from review_platform.review.proposal_validation import source_version, validate_proposal
from review_platform.review.schemas.proposals import ProposalInput, ProposalSpan

pytestmark = pytest.mark.no_db


def test_browser_coordinates_and_surrogate_boundaries():
    snapshot = uuid.uuid4()
    content = "A😀 support"
    body = ProposalInput(
        group_id="cited_cases",
        value="Citation",
        provenance=[
            ProposalSpan(
                source_snapshot_id=snapshot,
                source_version=source_version(content),
                char_start=1,
                char_end=3,
            )
        ],
    )
    validate_proposal(body, submitted=True, content=content, snapshot_id=snapshot)
    body.provenance[0].char_end = 2
    with pytest.raises(APIError, match="current source"):
        validate_proposal(body, submitted=True, content=content, snapshot_id=snapshot)


def test_duplicate_and_blank_marks_fail_and_empty_draft_is_valid():
    snapshot = uuid.uuid4()
    content = "Citation  "
    body = ProposalInput(group_id="cited_cases")
    validate_proposal(body, submitted=False, content=content, snapshot_id=snapshot)
    span = ProposalSpan(
        source_snapshot_id=snapshot,
        source_version=source_version(content),
        char_start=0,
        char_end=8,
    )
    body.provenance = [span, span]
    with pytest.raises(APIError):
        validate_proposal(body, submitted=False, content=content, snapshot_id=snapshot)
    body.provenance = [span.model_copy(update={"char_start": 8, "char_end": 10})]
    with pytest.raises(APIError):
        validate_proposal(body, submitted=False, content=content, snapshot_id=snapshot)
