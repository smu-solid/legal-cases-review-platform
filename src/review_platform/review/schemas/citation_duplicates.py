"""Reviewer-private duplicate feedback and content-bound acknowledgement."""

import uuid
from typing import Literal

from pydantic import Field

from review_platform.review.schemas.common import ReviewModel


class DuplicateAcknowledgement(ReviewModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000)


class CitationConflict(ReviewModel):
    item_id: uuid.UUID
    value: str
    kind: Literal["confirmed", "possible"]
    reason: str
    submitted: bool


class CitationDuplicateCheck(ReviewModel):
    fingerprint: str
    conflicts: list[CitationConflict] = Field(default_factory=list)


class ReviewerProvenanceContext(ReviewModel):
    item_id: uuid.UUID
    group_id: str
    value: str
    kind: Literal["Extracted", "Your correction", "Your added item"]
    superseded: bool = False
    source_snapshot_id: uuid.UUID
    source_version: str
    char_start: int
    char_end: int
