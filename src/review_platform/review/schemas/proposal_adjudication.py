"""Adjudication contracts preserve proposal IDs and their complete provenance sets."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from review_platform.review.schemas.common import ReviewModel
from review_platform.review.schemas.proposals import ProposalSpan, ReviewerProposal


class AdjudicationProposal(ReviewerProposal):
    reviewer_key: str
    reviewer_label: str
    proposal_number: int


class ProposalDecision(ReviewModel):
    outcome: Literal[
        "reviewer_preferred",
        "all_equivalent_supported",
        "all_wrong",
        "unsupported_or_not_locatable",
        "exceptional_skip",
    ]
    preferred_proposal_id: uuid.UUID | None = None
    preferred_submission_id: uuid.UUID | None = None
    corrected_value: str = Field(default="", max_length=10_000)
    provenance: list[ProposalSpan] = Field(default_factory=list, max_length=100)
    comment: str = Field(default="", max_length=10_000)

    @field_validator("corrected_value", "comment")
    @classmethod
    def reject_null_characters(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Null characters are not supported.")
        return value


class ProposalDecisionItem(ReviewModel):
    id: uuid.UUID
    group_id: str
    extracted_adjudication_id: uuid.UUID | None
    proposals: list[AdjudicationProposal]
    origin: Literal["automatic", "combined", "separated"]
    matching_reasons: list[str]
    different_values: bool
    reviewer_count: int
    state: Literal["pending", "submitted"]
    lock_version: int
    draft: ProposalDecision | None = None
    decision: ProposalDecision | None = None
    final_value: str | None = None
    final_provenance: list[ProposalSpan] = Field(default_factory=list)
    submitted_at: datetime | None = None


class ProposalAdjudicationWorkspace(ReviewModel):
    required_reviews: int = Field(ge=2)
    ready: bool
    items: list[ProposalDecisionItem]
    source_snapshot_id: uuid.UUID
    source_snapshot_ids: list[uuid.UUID] = Field(default_factory=list)
    source_version: str


class ProposalMembershipChange(ReviewModel):
    action: Literal["combine", "separate"]
    item_id: uuid.UUID
    expected_version: int = Field(ge=1)
    target_item_id: uuid.UUID | None = None
    target_version: int | None = Field(default=None, ge=1)
    target_extracted_id: uuid.UUID | None = None
    target_membership_version: int = Field(default=0, ge=0)
    confirm: bool


class ProposalDecisionWrite(ReviewModel):
    expected_version: int = Field(ge=1)
    decision: ProposalDecision
    submit: bool = False
