"""Reviewer selection and ``minimum_reviews_per_case`` are persisted inside
``Campaign.policy_json`` (no new column) alongside the existing
``required_reviews``/``authored`` keys; see ``review_platform.review.campaign_admin`` for
the read/write helpers."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from review_platform.review.schemas.admin import CampaignReviewScopeInput
from review_platform.review.schemas.campaign_availability import (
    CampaignCaseFilter,
    CampaignCaseIdSelection,
)
from review_platform.review.schemas.common import ReviewModel


class CampaignEditRequest(ReviewModel):
    """Edit campaign policy and save a case selection for future additions.

    ``campaign_key`` is never editable (immutable at the database level). Changing the source or
    case selector requires ``confirm=true``; ``closed`` campaigns cannot be edited. ``case_filter``
    and ``case_id_selection`` are mutually exclusive and a non-empty selection requires its
    matching source-bound Apply receipt. The selection remains active until changed or cleared.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_name: str | None = Field(default=None, min_length=1, max_length=200)
    review_scope: CampaignReviewScopeInput | None = None
    reviews_per_case: int | None = Field(
        default=None,
        ge=2,
        le=20,
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
    )
    case_filter: CampaignCaseFilter | None = None
    applied_filter_token: str | None = Field(default=None, max_length=4096)
    case_id_selection: CampaignCaseIdSelection | None = None
    applied_case_id_token: str | None = Field(default=None, max_length=4096)
    case_id_selection_file_name: str | None = Field(default=None, min_length=1, max_length=255)
    confirm: bool = False

    @model_validator(mode="after")
    def reject_multiple_case_selectors(self) -> CampaignEditRequest:
        if self.case_id_selection is not None and self.case_filter is not None:
            raise ValueError("case_filter and case_id_selection are mutually exclusive")
        if self.case_id_selection_file_name is not None and self.case_id_selection is None:
            raise ValueError("case_id_selection_file_name requires case_id_selection")
        return self


class CampaignDetailResponse(ReviewModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    status: str
    review_scope: CampaignReviewScopeInput | None
    reviews_per_case: int = Field(
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
    )
    selected_reviewer_ids: list[uuid.UUID]
    total_units: int
    synthesize_missing_values: bool = False
    case_filter: CampaignCaseFilter = Field(default_factory=CampaignCaseFilter)
    case_id_selection: CampaignCaseIdSelection | None = None
    case_id_selection_file_name: str | None = None
    # Derived, not stored: true iff a ``campaign.marked_completed`` audit event exists for this
    # campaign (see ``review_platform.review.campaign_lifecycle.mark_campaign_completed``). No new
    # campaign status -- "completed" is a manual, one-way, display-only milestone on a published
    # campaign.
    completed: bool = False
    schema_version: Literal["campaign-detail/v1"] = "campaign-detail/v1"


class CampaignDeleteResponse(ReviewModel):
    """A "delete" is a status transition to ``closed`` -- the ``campaigns`` table rejects hard
    ``DELETE`` at the database level ("close or supersede instead"), so draft removal is
    represented the same way a completed campaign's closure is.

    Deleting a draft returns its review units to the shared eligible-case pool (the inverse of
    ``materialize_from_pool``), so the freed cases become selectable by a future campaign;
    ``cases_returned_to_pool``/``units_returned_to_pool`` report how much was released.
    """

    campaign_id: uuid.UUID
    status: str
    cases_returned_to_pool: int = 0
    units_returned_to_pool: int = 0
    already_closed: bool = False
    schema_version: Literal["campaign-delete/v1"] = "campaign-delete/v1"


class CampaignReviewerAddRequest(ReviewModel):
    reviewer_id: uuid.UUID


class CampaignReviewersResponse(ReviewModel):
    campaign_id: uuid.UUID
    selected_reviewer_ids: list[uuid.UUID]
    schema_version: Literal["campaign-reviewers/v1"] = "campaign-reviewers/v1"


class CampaignAllocationPlanItem(ReviewModel):
    review_subject_id: uuid.UUID
    display_title: str
    reviewer_ids: list[uuid.UUID]


class CampaignAllocationSummaryResponse(ReviewModel):
    """Simple campaign allocation math: ``total_assignments = selected_cases *
    reviews_per_case`` (number of reviews per case), ``estimated_assignments_per_reviewer =
    ceil(total_assignments / selected_reviewers)``. ``assignment_plan`` is a read-only, seeded
    preview of a balanced case/reviewer plan -- publishing assignments still goes through the
    existing allocation-run preview/persist/publish endpoints."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_id: uuid.UUID
    selected_cases: int
    reviews_per_case: int = Field(
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
    )
    selected_reviewers: int
    # ``total_assignments`` is CASE level: (case, reviewer) pairs. ``total_unit_assignments`` is the
    # same plan in review units -- ``review_units * reviews_per_case`` -- which is what publishing
    # actually creates, and what the publish result and reviewer table report. Both are exposed so
    # the admin screen can name each granularity instead of silently mixing them.
    total_assignments: int
    review_units: int
    total_unit_assignments: int
    estimated_assignments_per_reviewer: int
    feasible: bool
    infeasible_reason: str | None
    infeasible_message: str | None
    assignment_plan: list[CampaignAllocationPlanItem]
    schema_version: Literal["campaign-allocation-summary/v1"] = "campaign-allocation-summary/v1"


class CampaignCaseProgressItem(ReviewModel):
    """Per-case progress row -- one row per distinct case, not per review unit."""

    case_id: str
    display_title: str
    review_kinds: list[str]
    field_group_labels: list[str]
    unit_count: int
    assignment_count: int
    submitted_count: int
    resolved_count: int
    reviewers_assigned_count: int
    reviewers_completed_count: int


class CampaignCaseProgressPage(ReviewModel):
    campaign_id: uuid.UUID
    items: list[CampaignCaseProgressItem]
    next_cursor: str | None = None
    has_more: bool = False
    schema_version: Literal["campaign-case-progress/v1"] = "campaign-case-progress/v1"
