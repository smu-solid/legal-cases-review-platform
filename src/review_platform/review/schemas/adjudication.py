"""Adjudication schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from review_platform.review.schemas.bundle import (
    CandidateAssessmentInput,
    CandidateResponse,
    EvidenceWindowResponse,
    ReviewSubjectResponse,
)
from review_platform.review.schemas.common import ReviewKind, ReviewModel
from review_platform.review.schemas.grouped_bundle import (
    AnchorUnavailableReason,
    GroupKind,
    ReviewerCaseHeader,
    SourceRender,
)
from review_platform.review.schemas.submissions import CorrectedProvenanceSpan


class AdjudicationFieldProgress(ReviewModel):
    review_unit_id: uuid.UUID
    item_label: str
    submitted_reviews: int = Field(ge=0)
    required_reviews: int = Field(ge=2)
    state: Literal["ready_for_me", "awaiting_reviews", "completed_by_me", "unavailable"]


class AdjudicationReviewerIdentity(ReviewModel):
    display_name: str | None = None
    email: str


class AdjudicationSummary(ReviewModel):
    display_title: str
    case_id: str
    campaign_id: uuid.UUID
    campaign_name: str
    workspace_adjudication_id: uuid.UUID | None = None
    ready_for_me_count: int = Field(ge=0)
    awaiting_reviews_count: int = Field(ge=0)
    completed_by_me_count: int = Field(ge=0)
    no_eligible_participant_count: int = Field(ge=0)
    total_field_count: int = Field(ge=1)
    item_count: int = Field(ge=0, description="Deprecated alias for ready_for_me_count.")
    submitted_review_slots: int = Field(ge=0)
    required_review_slots: int = Field(ge=2)
    field_progress: list[AdjudicationFieldProgress]
    exceptional_state: Literal["no_eligible_participants"] | None = None
    schema_version: Literal["adjudication-case-queue/v2"] = "adjudication-case-queue/v2"


class AdjudicationClaimResponse(ReviewModel):
    adjudication_id: uuid.UUID
    review_unit_id: uuid.UUID
    claimed_at: datetime
    adjudication_ids: list[uuid.UUID] = Field(default_factory=list)
    claimed_item_count: int = Field(default=1, ge=1)
    replayed: bool = False


class PseudonymousSubmission(ReviewModel):
    pseudonym: str
    outcome: str
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    assessments: list[CandidateAssessmentInput]
    evidence_ids: list[uuid.UUID]
    submitted_at: datetime


class AdjudicationBundle(ReviewModel):
    adjudication_id: uuid.UUID
    review_subject: ReviewSubjectResponse
    review_kind: ReviewKind
    candidates: list[CandidateResponse]
    evidence_windows: list[EvidenceWindowResponse]
    submissions: list[PseudonymousSubmission]
    schema_version: Literal["adjudication-bundle/v1"] = "adjudication-bundle/v1"


class PseudonymousGroupedSubmission(ReviewModel):
    submission_id: uuid.UUID
    pseudonym: str
    value_correct: bool
    provenance_correct: bool
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    failure_reason: str | None
    evidence_ids: list[uuid.UUID]
    corrected_provenance_spans: list[CorrectedProvenanceSpan] = Field(default_factory=list)
    submitted_at: datetime
    reviewer: AdjudicationReviewerIdentity | None = None


class AdjudicationAssessmentTarget(ReviewModel):
    """Opaque legacy decision target; validator/model details remain blinded."""

    id: uuid.UUID
    label: Literal["A", "B"]


class AdjudicationGroupedItem(ReviewModel):
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


class AdjudicationFieldGroup(ReviewModel):
    group_id: str
    group_label: str
    group_kind: GroupKind
    description: str | None = None
    order: int
    items: list[AdjudicationGroupedItem]


class AdjudicationGroupedBundle(ReviewModel):
    adjudication_id: uuid.UUID
    review_subject: ReviewSubjectResponse
    case_header: ReviewerCaseHeader
    case_id: str
    campaign_id: uuid.UUID
    campaign_name: str
    field_groups: list[AdjudicationFieldGroup]
    source_render: SourceRender
    pending_item_count: int = Field(ge=1)
    schema_version: Literal["adjudication-grouped-bundle/v2"] = "adjudication-grouped-bundle/v2"


class ReviewerAssessmentInput(ReviewModel):
    """Assessment of one opaque, pseudonymous reviewer submission."""

    submission_id: uuid.UUID
    assessment: Literal["correct", "incorrect", "not_assessable"]


AdjudicationOutcome = Literal[
    "candidate_a_preferred",
    "candidate_b_preferred",
    "equivalent_supported",
    "both_wrong",
    "unsupported_or_not_locatable",
    "exceptional_skip",
    "reviewer_assessments_recorded",
    "reviewer_preferred",
    "all_equivalent_supported",
    "all_wrong",
]


class AdjudicationDraftInput(ReviewModel):
    """Work in progress, including a private note before a verdict has been selected."""

    outcome: AdjudicationOutcome | None = None
    assessments: list[CandidateAssessmentInput] = Field(default_factory=list, max_length=2)
    reviewer_assessments: list[ReviewerAssessmentInput] = Field(default_factory=list)
    membership_version: int = Field(default=0, ge=0)
    preferred_proposal_id: uuid.UUID | None = None
    preferred_submission_id: uuid.UUID | None = None
    corrected_value: JsonValue | None = None
    corrected_value_display: str | None = Field(default=None, max_length=10_000)
    comment: str | None = Field(default=None, max_length=20_000)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    corrected_provenance_spans: list[CorrectedProvenanceSpan] = Field(
        default_factory=list, max_length=100
    )


class AdjudicationDecisionInput(AdjudicationDraftInput):
    """Final decision for either the legacy A/B flow or grouped reviewer submissions."""

    outcome: AdjudicationOutcome


class AdjudicationDraftResponse(ReviewModel):
    adjudication_id: uuid.UUID
    decision: AdjudicationDraftInput
    saved_at: datetime
    replayed: bool = False
    schema_version: Literal["adjudication-draft/v2"] = "adjudication-draft/v2"


class AdjudicationDecisionResponse(ReviewModel):
    decision_id: uuid.UUID
    adjudication_id: uuid.UUID
    review_unit_id: uuid.UUID
    status: Literal["submitted", "resolved"]
    outcome: str
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    assessments: list[CandidateAssessmentInput]
    reviewer_assessments: list[ReviewerAssessmentInput]
    preferred_proposal_id: uuid.UUID | None = None
    preferred_submission_id: uuid.UUID | None
    evidence_ids: list[uuid.UUID]
    corrected_provenance_spans: list[CorrectedProvenanceSpan]
    decided_at: datetime
    replayed: bool = False
    schema_version: Literal["adjudication-decision/v2"] = "adjudication-decision/v2"
