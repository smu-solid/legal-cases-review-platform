"""Reviewer-authored citations; deliberately separate from extracted-field answers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from review_platform.review.schemas.citation_duplicates import DuplicateAcknowledgement
from review_platform.review.schemas.common import ReviewModel
from review_platform.review.schemas.submissions import ReviewItemAnswerInput


class ProposalSpan(ReviewModel):
    source_snapshot_id: uuid.UUID
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def ordered(self) -> ProposalSpan:
        if self.char_end <= self.char_start:
            raise ValueError("The marked range must be nonempty and ordered.")
        return self


class ProposalInput(ReviewModel):
    duplicate_acknowledgement: DuplicateAcknowledgement | None = None
    group_id: str = Field(max_length=60)
    value: str = Field(default="", max_length=10_000)
    note: str = Field(default="", max_length=10_000)
    provenance: list[ProposalSpan] = Field(default_factory=list, max_length=100)

    @field_validator("value", "note")
    @classmethod
    def database_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Text cannot contain a null character.")
        return value


class ReviewerProposal(ProposalInput):
    id: uuid.UUID
    value_schema: Literal["cited_case_text/v1", "statute_reference_text/v1"]
    original_value: str
    state: Literal["draft", "submitted", "removed"]
    lock_version: int
    created_at: datetime
    submitted_at: datetime | None = None


class ProposalDuplicateInput(ProposalInput):
    answer_overrides: dict[uuid.UUID, ReviewItemAnswerInput] = Field(default_factory=dict)
