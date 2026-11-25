"""Review administration request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, ConfigDict, Field, JsonValue, model_validator

from review_platform.review.grouping import GROUP_BY_ID, SOURCE_FAMILIES
from review_platform.review.schemas.bundle import CandidateAssessmentInput
from review_platform.review.schemas.campaign_availability import (
    CampaignAvailabilityResponse,
    CampaignCaseFilter,
    CampaignCaseIdSelection,
)
from review_platform.review.schemas.common import ReviewKind, ReviewModel, SubjectKind


class CampaignReviewScopeInput(ReviewModel):
    group_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional backend-owned grouped-bundle group ids to include.",
    )
    review_kinds: list[ReviewKind] = Field(
        default_factory=list,
        max_length=20,
        description="Optional review kinds to include. Empty means all review kinds.",
    )
    source_families: list[str] = Field(
        default_factory=list,
        max_length=len(SOURCE_FAMILIES),
        description="Optional source systems to include (e.g. 'sample_a', 'sample_b'). Empty "
        "means all sources.",
    )

    @model_validator(mode="after")
    def _validate_group_ids(self) -> CampaignReviewScopeInput:
        unknown = sorted(set(self.group_ids) - GROUP_BY_ID.keys())
        if unknown:
            raise ValueError(f"unknown review group id(s): {unknown}")
        return self

    @model_validator(mode="after")
    def _validate_source_families(self) -> CampaignReviewScopeInput:
        unknown = sorted(set(self.source_families) - set(SOURCE_FAMILIES))
        if unknown:
            raise ValueError(f"unknown source family/families: {unknown}")
        return self


class CampaignScopeGroup(ReviewModel):
    """One selectable field group in the backend-owned scope catalog."""

    group_id: str
    group_label: str
    group_kind: Literal["atomic", "non_atomic"]
    order: int
    description: str | None = None


class CampaignScopeCatalogResponse(ReviewModel):
    """Backend-owned catalog of the field groups and review kinds a campaign scope may select."""

    tenant_id: uuid.UUID
    groups: list[CampaignScopeGroup]
    review_kinds: list[ReviewKind]
    contract_version: Literal["campaign-scope-catalog/v1"] = "campaign-scope-catalog/v1"


class SyntheticImportRequest(ReviewModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fixture_version: Literal["v0001"]
    campaign_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    campaign_name: str = Field(min_length=1, max_length=200)
    review_scope: CampaignReviewScopeInput | None = None
    case_count: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap on imported review units, applied after review_scope filtering "
        "in fixture order. None imports every in-scope unit. The synthetic fixture is a small, "
        "fixed set (see fixtures/dataset_contracts/v0001) -- a count above what's in scope imports "
        "everything in scope rather than fabricating additional units.",
    )
    reviewer_count: Literal[0] = Field(
        default=0,
        description="Reviewers are always 0 at import time and assigned manually afterwards via "
        "the roster/allocation endpoints; automatic reviewer assignment at import is not "
        "implemented.",
    )
    reviews_per_case: int | None = Field(
        default=None,
        ge=2,
        le=20,
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
        description="Number of reviews per case before a unit is submitted/resolved. Defaults to "
        "2. Only takes effect the first time a campaign key is created; a later import into an "
        "existing campaign uses that campaign's already-persisted value (see editCampaign to "
        "change it beforehand).",
    )


class SyntheticImportResponse(ReviewModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_id: uuid.UUID
    fixture_version: str
    manifest_digest: str
    imported_units: int
    blocked_units: int
    review_scope: CampaignReviewScopeInput | None = None
    reviews_per_case: int = Field(
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
    )
    replayed: bool
    source_mode: Literal["synthetic"] = "synthetic"


class CreateCampaignRequest(ReviewModel):
    """Author a draft campaign, optionally materialized from the preloaded eligible case pool."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    campaign_name: str = Field(min_length=1, max_length=200)
    review_scope: CampaignReviewScopeInput | None = None
    reviews_per_case: int | None = Field(
        default=None,
        ge=2,
        le=20,
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
        description="Number of reviews per case before a unit is submitted/resolved. Defaults "
        "to 2.",
    )
    requested_case_count: int | Literal["all"] | None = Field(
        default=None,
        description="Positive integer or 'all'. Omit to author an empty draft with no review "
        "units (legacy behavior); provide to materialize the draft from the eligible pool.",
    )
    confirm_smaller_count: bool = Field(
        default=False,
        description="Required when fewer eligible cases exist than requested_case_count.",
    )
    confirm_remaining_fields_only: bool = Field(
        default=False,
        description="Required when no case has every selected field available, but some cases "
        "have a subset of the selected fields remaining.",
    )
    synthesize_missing_values: bool = Field(
        default=False,
        description="Opt-in (default off). When true, a case missing a selected field group gets "
        "an explicit 'missing' review unit synthesized instead of being excluded from "
        "eligibility. Default-off "
        "keeps existing campaign flows byte-for-byte unaffected; the flag is persisted on the "
        "campaign so later top-ups (load_pool_cases) reuse the same decision.",
    )
    case_filter: CampaignCaseFilter | None = None
    applied_filter_token: str | None = Field(default=None, max_length=4096)
    case_id_selection: CampaignCaseIdSelection | None = None
    applied_case_id_token: str | None = Field(default=None, max_length=4096)
    case_id_selection_file_name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def reject_conflicting_missing_policies(self) -> CreateCampaignRequest:
        if self.confirm_remaining_fields_only and self.synthesize_missing_values:
            raise ValueError(
                "confirm_remaining_fields_only cannot be combined with synthesize_missing_values"
            )
        if self.case_id_selection is not None and self.case_filter is not None:
            raise ValueError("case_filter and case_id_selection are mutually exclusive")
        if self.case_id_selection_file_name is not None and self.case_id_selection is None:
            raise ValueError("case_id_selection_file_name requires case_id_selection")
        return self


class CreateCampaignResponse(ReviewModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    status: str
    total_units: int = 0
    review_scope: CampaignReviewScopeInput | None = None
    reviews_per_case: int = Field(
        validation_alias=AliasChoices("reviews_per_case", "minimum_reviews_per_case"),
        serialization_alias="reviews_per_case",
    )
    availability: CampaignAvailabilityResponse | None = None
    not_ready_for_publish: bool = False
    schema_version: Literal["campaign-authored/v1"] = "campaign-authored/v1"


class AssignmentRevisionRequestInput(ReviewModel):
    reason: str = Field(
        min_length=1,
        max_length=1_000,
        description="Reviewer-visible reason for returning the submitted assignment for revision.",
    )


class AdminReviewSubmission(ReviewModel):
    submission_id: uuid.UUID
    assignment_id: uuid.UUID
    review_unit_id: uuid.UUID
    reviewer_id: uuid.UUID
    subject_kind: SubjectKind
    review_kind: ReviewKind
    display_title: str
    outcome: str
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    assessments: list[CandidateAssessmentInput]
    evidence_ids: list[uuid.UUID]
    submitted_at: datetime


class AdminReviewSubmissionPage(ReviewModel):
    items: list[AdminReviewSubmission]
    next_cursor: str | None = None
    has_more: bool = False


class ReviewerPairAgreement(ReviewModel):
    reviewer_a_id: uuid.UUID
    reviewer_b_id: uuid.UUID
    pair_count: int
    agree_count: int
    agreement_percent: float | None
    cohen_kappa: float | None
    pabak: float | None
    labels: list[str]
    confusion: dict[str, dict[str, int]]


class ReviewerAgreementMetricsResponse(ReviewModel):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID | None
    review_kind: ReviewKind | None
    review_unit_count: int
    submission_count: int
    pair_count: int
    agree_count: int
    agreement_percent: float | None
    cohen_kappa: float | None
    pabak: float | None
    labels: list[str]
    confusion: dict[str, dict[str, int]]
    reviewer_pairs: list[ReviewerPairAgreement]
    schema_version: Literal["reviewer-agreement-metrics/v1"] = "reviewer-agreement-metrics/v1"


class CampaignUnitStatusCounts(ReviewModel):
    pending: int
    in_review: int
    in_adjudication: int
    resolved: int


class CampaignAssignmentStatusCounts(ReviewModel):
    claimed: int
    submitted: int
    released: int


class CampaignProgressItem(ReviewModel):
    campaign_id: uuid.UUID
    campaign_name: str
    campaign_key: str
    campaign_status: str
    cases_total: int
    total_units: int
    unit_status_counts: CampaignUnitStatusCounts
    total_assignments: int
    assignment_status_counts: CampaignAssignmentStatusCounts
    reviewers_total: int
    # Case-level progress: every case is expected to be reviewed by exactly ``reviews_per_case``
    # distinct reviewers (the number-of-reviews-per-case policy), NOT by every selected reviewer on
    # the roster -- the allocator assigns each case exactly that many reviewers, so the total
    # "slots" to fill is cases_total * reviews_per_case (= total planned assignments), never
    # cases_total * reviewers_total. A slot is filled only by an explicit CaseSubmission, never
    # derived from "every field happens to be submitted" alone.
    case_reviewer_slots_total: int
    case_reviewer_completions: int
    # A case is "fully complete" only once every reviewer actually assigned to it (not necessarily
    # every one of the campaign's selected reviewers -- see the per-case "Reviewers done" column's
    # same definition in CampaignCaseProgressItem) has an explicit CaseSubmission for it. Distinct
    # from case_reviewer_completions/case_reviewer_slots_total, which count reviewer-case slots, not
    # whole cases.
    cases_fully_complete_count: int
    # Derived, not stored: true iff a ``campaign.marked_completed`` audit event exists for this
    # campaign -- see ``CampaignDetailResponse.completed`` for the same manual, one-way milestone.
    completed: bool = False
    schema_version: Literal["campaign-progress/v1"] = "campaign-progress/v1"


class CampaignProgressResponse(ReviewModel):
    tenant_id: uuid.UUID
    items: list[CampaignProgressItem]
    schema_version: Literal["campaign-progress-list/v1"] = "campaign-progress-list/v1"


class ReviewerWorkloadItem(ReviewModel):
    reviewer_id: uuid.UUID
    total_assignments: int
    submitted_count: int
    claimed_count: int
    released_count: int
    # Same "has work" definition the remove-reviewer guard enforces server-side
    # (``campaign_reviewer_work_exists``): saved answers, submitted, or revision-requested work.
    # Lets the UI freeze the remove control before the click, not just react to its rejection.
    has_work: bool = False


class ReviewerWorkloadResponse(ReviewModel):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    items: list[ReviewerWorkloadItem]
    schema_version: Literal["reviewer-workload/v1"] = "reviewer-workload/v1"
