"""Reviewer queue schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from review_platform.review.schemas.common import ReviewKind, ReviewModel, SubjectKind


class ReviewQueueItem(ReviewModel):
    review_unit_id: uuid.UUID
    assignment_id: uuid.UUID | None = None
    assignment_status: Literal["available", "assigned", "completed"] = "available"
    campaign_id: uuid.UUID
    # Real case identity (``snapshot_local_case_external_id``), the same grouping key used by the
    # admin per-case table, the grouped bundle, and ``ReviewerCaseQueueItem`` -- lets the UI group
    # flat per-field queue rows by case (e.g. a "claim the whole case" action) without a second
    # call.
    case_id: str
    subject_kind: SubjectKind
    review_kind: ReviewKind
    display_title: str
    display_subtitle: str | None
    safe_field_label: str


class ReviewQueuePage(ReviewModel):
    items: list[ReviewQueueItem]
    next_cursor: str | None = None
    has_more: bool = False


class ReviewerCampaignSummary(ReviewModel):
    """Per-campaign reviewer queue summary: identity, own-work counts, and selected fields.

    Counts are scoped to the calling reviewer only (no peer-reviewer leakage): ``not_started``
    is the open pool still claimable by this reviewer, ``in_progress`` is this reviewer's own
    claimed-but-unsubmitted assignments, and ``completed`` is this reviewer's own submitted
    assignments in the campaign.
    """

    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    not_started_count: int
    in_progress_count: int
    completed_count: int
    selected_group_ids: list[str]


class ReviewerCampaignQueuePage(ReviewModel):
    campaigns: list[ReviewerCampaignSummary]
    next_cursor: str | None = None
    has_more: bool = False
    schema_version: Literal["reviewer-campaign-queue/v1"] = "reviewer-campaign-queue/v1"


class ReviewerCaseQueueItem(ReviewModel):
    """One distinct case the reviewer holds at least one assignment for in this campaign.

    Aggregates every review unit/field the reviewer owns for the case (grouped by
    ``snapshot_local_case_external_id``, the same real case identity used by the admin
    per-case table and the grouped bundle) -- never one row per field.
    ``anchor_assignment_id`` opens the case's grouped workspace (``GET
    .../grouped-bundle``), which itself re-derives the full field set from any one of
    the case's assignments."""

    case_id: str
    case_title: str
    neutral_citation_display: str | None = None
    reported_citation_display: str | None = None
    campaign_id: uuid.UUID
    anchor_assignment_id: uuid.UUID
    fields_assigned: int
    fields_submitted: int
    status: Literal["not_started", "in_progress", "completed"]


class ReviewerCaseQueuePage(ReviewModel):
    campaign_id: uuid.UUID
    items: list[ReviewerCaseQueueItem]
    next_cursor: str | None = None
    has_more: bool = False
    schema_version: Literal["reviewer-case-queue/v1"] = "reviewer-case-queue/v1"


class ClaimRequest(ReviewModel):
    review_unit_id: uuid.UUID | None = Field(
        default=None,
        description="Optional targeted review unit to claim; omit to claim the next eligible unit.",
    )
    subject_kind: SubjectKind | None = Field(
        default=None,
        description="Optional next-claim filter matching the queue subject_kind filter.",
    )
    review_kind: ReviewKind | None = Field(
        default=None,
        description="Optional next-claim filter matching the queue review_kind filter.",
    )
    campaign_id: uuid.UUID | None = Field(
        default=None,
        description="Optional next-claim filter restricting the claim to one campaign.",
    )
