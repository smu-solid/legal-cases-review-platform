"""Campaign-first, caller-personalized adjudication read models."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

from review_platform.review.schemas.adjudication import (
    AdjudicationAssessmentTarget,
    AdjudicationDecisionResponse,
    AdjudicationDraftResponse,
    AdjudicationReviewerIdentity,
    PseudonymousGroupedSubmission,
)
from review_platform.review.schemas.bundle import EvidenceWindowResponse
from review_platform.review.schemas.common import ReviewKind, ReviewModel
from review_platform.review.schemas.grouped_bundle import (
    AnchorUnavailableReason,
    GroupKind,
    ReviewerCaseHeader,
    SourceRender,
)

AdjudicationCaseStatus = Literal["waiting", "in_progress", "finished", "not_required"]
AdjudicationCompletionKind = Literal[
    "completed",
    "not_required",
    "waived",
    "completed_with_waiver",
]
AdjudicationCampaignFieldState = Literal[
    "awaiting_reviews",
    "ready_for_adjudication",
    "adjudicated_by_me",
    "not_assigned_to_me",
    "unavailable",
]


class AdjudicationResponsibilityProgress(ReviewModel):
    total_scoped_fields: int = Field(ge=0)
    personal_responsibility_fields: int = Field(ge=0)
    completed_responsibility_fields: int = Field(ge=0)
    submitted_fields: int = Field(ge=0)
    waived_fields: int = Field(ge=0)
    not_required_fields: int = Field(ge=0)
    pending_fields: int = Field(ge=0)
    future_eligible_fields: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partition(self) -> AdjudicationResponsibilityProgress:
        if self.personal_responsibility_fields != (
            self.submitted_fields
            + self.waived_fields
            + self.pending_fields
            + self.future_eligible_fields
        ):
            raise ValueError("personal responsibility fields must equal their disjoint partition")
        if self.completed_responsibility_fields != self.submitted_fields + self.waived_fields:
            raise ValueError("completed responsibility fields must equal submitted plus waived")
        if self.completed_responsibility_fields > self.personal_responsibility_fields:
            raise ValueError("completed responsibility cannot exceed personal responsibility")
        if self.total_scoped_fields != (
            self.personal_responsibility_fields + self.not_required_fields
        ):
            raise ValueError("scoped fields must equal personal responsibility plus not required")
        return self


class AdjudicationCampaignFieldProgress(ReviewModel):
    proposal_item_id: uuid.UUID | None = None
    review_unit_id: uuid.UUID
    item_label: str
    submitted_reviews: int = Field(ge=0)
    required_reviews: int = Field(ge=2)
    state: AdjudicationCampaignFieldState
    pending_reviewers: list[AdjudicationReviewerIdentity] = Field(default_factory=list)


class AdjudicationCampaignSummary(ReviewModel):
    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    waiting_count: int = Field(ge=0)
    in_progress_count: int = Field(ge=0)
    finished_count: int = Field(ge=0)
    not_required_count: int = Field(ge=0)
    total_case_count: int = Field(ge=0)


class AdjudicationCampaignQueuePage(ReviewModel):
    campaigns: list[AdjudicationCampaignSummary]
    next_cursor: str | None = None
    has_more: bool = False
    schema_version: Literal["adjudication-campaign-queue/v1"] = "adjudication-campaign-queue/v1"


class AdjudicationCampaignCaseItem(ReviewModel):
    case_id: str
    campaign_id: uuid.UUID
    case_title: str
    neutral_citation_display: str | None = None
    reported_citation_display: str | None = None
    status: AdjudicationCaseStatus
    completion_kind: AdjudicationCompletionKind | None = None
    status_reason_code: str
    status_reason: str
    progress: AdjudicationResponsibilityProgress
    field_progress: list[AdjudicationCampaignFieldProgress]
    workspace_adjudication_id: uuid.UUID | None = None
    workspace_mode: Literal["edit", "read_only"] | None = None


class AdjudicationCampaignCaseCounts(ReviewModel):
    all: int = Field(ge=0)
    waiting: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    finished: int = Field(ge=0)
    not_required: int = Field(ge=0)


class AdjudicationCampaignCaseQueuePage(ReviewModel):
    campaign: AdjudicationCampaignSummary
    counts: AdjudicationCampaignCaseCounts
    items: list[AdjudicationCampaignCaseItem]
    next_cursor: str | None = None
    has_more: bool = False
    schema_version: Literal["adjudication-campaign-case-queue/v1"] = (
        "adjudication-campaign-case-queue/v1"
    )


class AdjudicationCaseNeighbors(ReviewModel):
    previous_open: AdjudicationCampaignCaseItem | None = None
    next_open: AdjudicationCampaignCaseItem | None = None
    schema_version: Literal["adjudication-case-neighbors/v1"] = "adjudication-case-neighbors/v1"


class AdjudicationWorkspaceItem(ReviewModel):
    membership_version: int = 0
    adjudication_id: uuid.UUID
    review_unit_id: uuid.UUID
    item_id: str
    item_label: str
    item_kind: str
    extracted_value_display: str
    review_kind: ReviewKind
    required_reviews: int = Field(ge=2)
    submitted_reviews: int = Field(ge=0)
    source_anchor_id: str | None = None
    source_anchor_unavailable_reason: AnchorUnavailableReason | None = None
    evidence_window_ids: list[uuid.UUID]
    assessment_targets: list[AdjudicationAssessmentTarget] = Field(default_factory=list)
    evidence_windows: list[EvidenceWindowResponse] = Field(default_factory=list)
    submissions: list[PseudonymousGroupedSubmission]
    draft: AdjudicationDraftResponse | None = None
    participation_status: Literal["pending", "submitted"]
    submitted_decision: AdjudicationDecisionResponse | None = None


class AdjudicationWorkspaceFieldGroup(ReviewModel):
    group_id: str
    group_label: str
    group_kind: GroupKind
    description: str | None = None
    order: int
    items: list[AdjudicationWorkspaceItem]


class AdjudicationCaseWorkspace(ReviewModel):
    anchor_adjudication_id: uuid.UUID
    case_id: str
    campaign: AdjudicationCampaignSummary
    case: AdjudicationCampaignCaseItem
    case_header: ReviewerCaseHeader
    field_groups: list[AdjudicationWorkspaceFieldGroup]
    source_render: SourceRender
    mode: Literal["edit", "read_only"]
    schema_version: Literal["adjudication-case-workspace/v1"] = "adjudication-case-workspace/v1"
