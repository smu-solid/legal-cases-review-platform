"""Reviewer value/provenance item answer schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from review_platform.review.schemas.common import ReviewModel


class CorrectedProvenanceSpan(ReviewModel):
    source_snapshot_id: uuid.UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_version: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", exclude_if=lambda value: value is None
    )
    evidence_window_id: uuid.UUID
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_order(self) -> CorrectedProvenanceSpan:
        if (self.source_snapshot_id is None) != (self.source_version is None):
            raise ValueError("Source identity and version must be supplied together")
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class ReviewItemAnswerInput(ReviewModel):
    value_correct: bool | None = None
    provenance_correct: bool | None = None
    corrected_value: JsonValue | None = None
    corrected_value_display: str | None = Field(default=None, max_length=10_000)
    comment: str | None = Field(default=None, max_length=20_000)
    failure_reason: str | None = Field(default=None, min_length=1, max_length=80)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    corrected_provenance_spans: list[CorrectedProvenanceSpan] = Field(
        default_factory=list, max_length=100
    )


class ReviewItemAnswerResponse(ReviewModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    review_unit_id: uuid.UUID
    revision_no: int
    state: Literal["draft", "submitted"]
    value_correct: bool | None
    provenance_correct: bool | None
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    failure_reason: str | None
    evidence_ids: list[uuid.UUID]
    corrected_provenance_spans: list[CorrectedProvenanceSpan]
    created_at: datetime
    lock_version: int
    replayed: bool = False
    schema_version: Literal["reviewer-item-answer/v1"] = "reviewer-item-answer/v1"
