"""Grouped reviewer workspace bundle schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, JsonValue

from review_platform.review.schemas.bundle import EvidenceWindowResponse
from review_platform.review.schemas.citation_duplicates import ReviewerProvenanceContext
from review_platform.review.schemas.common import ReviewModel, SubjectKind
from review_platform.review.schemas.proposals import ReviewerProposal
from review_platform.review.schemas.submissions import CorrectedProvenanceSpan

GroupKind = Literal["atomic", "non_atomic"]
GroupItemStatus = Literal["not_started", "draft", "submitted", "skipped"]
ScrollHint = Literal["start", "center", "nearest"]
RenderMode = Literal["safe_text", "sanitized_html"]
AnchorUnavailableReason = Literal[
    "no_evidence",
    "source_truncated",
    "anchor_budget_exhausted",
    "out_of_scope",
    "anchor_unresolved",
    # Every window of the unit belongs to another document of the same family: nothing is wrong
    # with the anchor, the rendered document simply is not the one the evidence was taken from.
    "other_document",
]


class ReviewerCaseHeader(ReviewModel):
    subject_id: uuid.UUID
    subject_kind: SubjectKind
    case_title: str
    case_identifier_display: str
    neutral_citation_display: str | None = None
    reported_citation_display: str | None = None
    source_system: str | None = None
    campaign_name: str | None = None


class SourceAnchor(ReviewModel):
    anchor_id: str
    review_unit_id: uuid.UUID | None = None
    group_id: str | None = None
    item_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    scroll_hint: ScrollHint = "nearest"
    label: str | None = None


class SourceRender(ReviewModel):
    source_snapshot_id: uuid.UUID
    render_mode: RenderMode
    content: str
    anchors: list[SourceAnchor]
    truncated: bool = False
    omitted_anchor_count: int = 0


class ItemAnswerSummary(ReviewModel):
    state: Literal["draft", "submitted"]
    value_correct: bool | None
    provenance_correct: bool | None
    corrected_value_display: str | None = None
    comment: str | None = None
    failure_reason: str | None = None
    corrected_provenance_spans: list[CorrectedProvenanceSpan] = []


class MemberSourceValue(ReviewModel):
    """One family member observation's value for this field, source-labelled.

    Served whenever the canonical family holds more than one source observation; the reviewer
    adjudicates between the sources instead of one being silently preferred. ``value`` is a
    bounded PREVIEW (``value_truncated`` marks the cut); the full value and complete evidence stay
    on the review subject's attributes, which the same bundle serves.
    """

    case: str
    source_system: str
    value: str
    value_truncated: bool = False
    source_document_id: str | None = None
    source_sha256: str | None = None
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)


class GroupItem(ReviewModel):
    review_unit_id: uuid.UUID
    assignment_id: uuid.UUID
    item_id: str
    item_label: str
    item_kind: str
    #: Family review: every member observation's value (root first) and whether they disagree.
    member_values: list[MemberSourceValue] = Field(default_factory=list)
    cross_source_disagreement: bool = False
    ordinal: int | None = None
    extracted_value_display: str
    extracted_value_raw: JsonValue | None = None
    normalized_value: JsonValue | None = None
    source_anchor_id: str | None = None
    source_anchor_unavailable_reason: AnchorUnavailableReason | None = None
    evidence_window_ids: list[uuid.UUID]
    #: The same windows, projected with anchor status and the grounded-in descriptor, so the
    #: workspace can say WHERE evidence lives when it cannot be highlighted in this document.
    evidence_windows: list[EvidenceWindowResponse] = Field(default_factory=list)
    status: GroupItemStatus
    answer_summary: ItemAnswerSummary | None = None
    lock_version: int
    extraction_state: Literal["present", "missing"] = "present"


class FieldGroup(ReviewModel):
    add_item_label: str | None = None
    group_id: str
    group_label: str
    group_kind: GroupKind
    description: str | None = None
    order: int
    item_count: int
    completed_count: int
    group_anchor_id: str | None = None
    items: list[GroupItem]


class GroupProgress(ReviewModel):
    group_id: str
    item_count: int
    completed_count: int


class GroupedProgress(ReviewModel):
    total_items: int
    completed_items: int
    remaining_items: int
    group_progress: list[GroupProgress]


class ReviewerGroupingBundle(ReviewModel):
    provenance_context: list[ReviewerProvenanceContext] = Field(default_factory=list)
    proposal_source_snapshot_ids: list[uuid.UUID] = Field(default_factory=list)
    reviewer_additions: list[ReviewerProposal] = Field(default_factory=list)
    proposal_source_version: str | None = None
    case_submitted: bool = False
    case_header: ReviewerCaseHeader
    field_groups: list[FieldGroup]
    source_render: SourceRender
    progress: GroupedProgress
    allowed_actions: list[Literal["save_draft", "submit"]]
    lock_version: int
    schema_version: Literal["reviewer-grouping-bundle/v1"] = "reviewer-grouping-bundle/v1"
