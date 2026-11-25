"""Campaign availability/feasibility schemas against the preloaded eligible case pool."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from review_platform.review.schemas.common import ReviewModel

FeasibilityStatus = Literal[
    "feasible_exact",
    "feasible_with_smaller_count",
    "feasible_with_remaining_fields_only",
    "infeasible_no_cases",
    "infeasible_no_fields",
]

# "all" preloads/selects every eligible case; a positive integer caps the request.
CaseCountInput = int | Literal["all"]
MAX_UPLOADED_CASE_IDS = 10_000
MAX_CASE_ID_LENGTH = 200


class CampaignJudgmentYearRange(ReviewModel):
    start: int = Field(ge=1000, le=9999)
    end: int = Field(ge=1000, le=9999)

    @model_validator(mode="after")
    def reject_reversed_range(self) -> CampaignJudgmentYearRange:
        if self.start > self.end:
            raise ValueError("judgment year range start must not exceed its end")
        return self


class CampaignJudgmentYearValue(ReviewModel):
    ranges: list[CampaignJudgmentYearRange] = Field(min_length=1, max_length=62)

    @model_validator(mode="after")
    def normalize_ranges(self) -> CampaignJudgmentYearValue:
        merged: list[CampaignJudgmentYearRange] = []
        for item in sorted(self.ranges, key=lambda value: (value.start, value.end)):
            if merged and item.start <= merged[-1].end + 1:
                merged[-1] = CampaignJudgmentYearRange(
                    start=merged[-1].start, end=max(merged[-1].end, item.end)
                )
            else:
                merged.append(item)
        self.ranges = merged
        return self


class CampaignCaseFilterClause(ReviewModel):
    field_id: Literal["case_subject", "judgment_year"]
    operator: Literal["contains_ci", "eq", "in_ranges"]
    value: str | int | CampaignJudgmentYearValue

    @model_validator(mode="after")
    def validate_pair(self) -> CampaignCaseFilterClause:
        if self.field_id == "case_subject":
            if self.operator != "contains_ci" or not isinstance(self.value, str):
                raise ValueError("case_subject requires contains_ci and a text value")
            value = self.value.strip()
            if not 1 <= len(value) <= 200:
                raise ValueError("case subject must be between 1 and 200 characters")
            self.value = value
            return self
        if (
            self.operator == "eq"
            and not isinstance(self.value, bool)
            and isinstance(self.value, int)
        ):
            self.operator = "in_ranges"
            self.value = CampaignJudgmentYearValue(
                ranges=[CampaignJudgmentYearRange(start=self.value, end=self.value)]
            )
        if self.operator != "in_ranges" or not isinstance(self.value, CampaignJudgmentYearValue):
            raise ValueError("judgment_year requires one or more year ranges")
        return self


class CampaignCaseFilter(ReviewModel):
    version: Literal["v1"] = "v1"
    all: list[CampaignCaseFilterClause] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def reject_duplicate_fields(self) -> CampaignCaseFilter:
        fields = [clause.field_id for clause in self.all]
        if len(fields) != len(set(fields)):
            raise ValueError("duplicate case-filter fields are not supported")
        return self


class CampaignCaseFilterApplyRequest(ReviewModel):
    source_families: list[str] = Field(default_factory=list)
    case_filter: CampaignCaseFilter = Field(default_factory=CampaignCaseFilter)


class CampaignCaseFilterApplyResponse(ReviewModel):
    normalized_case_filter: CampaignCaseFilter
    source_pool_cases_count: int
    case_filter_matching_count: int
    matching_count_by_source: dict[Literal["sample_a", "sample_b"], int]
    unidentifiable_pool_units_count: int = 0
    identity_unavailable_cases_count: int = 0
    identity_conflict_cases_count: int = 0
    catalog_result_digest: str
    receipt_expires_at: datetime
    applied_filter_token: str
    schema_version: Literal["campaign-case-filter-apply/v1"] = "campaign-case-filter-apply/v1"


class CampaignCaseIdSelection(ReviewModel):
    version: Literal["v1"] = "v1"
    case_ids: list[str] = Field(min_length=1, max_length=MAX_UPLOADED_CASE_IDS)

    @field_validator("case_ids")
    @classmethod
    def normalize_case_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for index, value in enumerate(values):
            case_id = value.lstrip("\ufeff").strip() if index == 0 else value.strip()
            if not case_id:
                continue
            if len(case_id) > MAX_CASE_ID_LENGTH:
                raise ValueError(f"case IDs must not exceed {MAX_CASE_ID_LENGTH} characters")
            if case_id not in seen:
                normalized.append(case_id)
                seen.add(case_id)
        if not normalized:
            raise ValueError("at least one non-empty case ID is required")
        return normalized


class CampaignCaseIdApplyRequest(ReviewModel):
    source_families: list[str] = Field(default_factory=list)
    case_id_selection: CampaignCaseIdSelection


class CampaignCaseIdApplyResponse(ReviewModel):
    normalized_case_id_selection: CampaignCaseIdSelection
    source_pool_cases_count: int
    uploaded_unique_count: int
    case_id_matching_count: int
    matching_count_by_source: dict[Literal["sample_a", "sample_b"], int]
    unmatched_case_ids: list[str]
    receipt_expires_at: datetime
    applied_case_id_token: str
    schema_version: Literal["campaign-case-id-apply/v1"] = "campaign-case-id-apply/v1"


class CampaignCaseFilterExportRequest(ReviewModel):
    source_families: list[str] = Field(default_factory=list)
    case_filter: CampaignCaseFilter = Field(default_factory=CampaignCaseFilter)
    applied_filter_token: str | None = Field(default=None, max_length=4096)


class CampaignCaseFilterCorrectionRequest(ReviewModel):
    field_id: Literal["case_subject"]
    query: str = Field(min_length=3, max_length=200)
    source_families: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("query must contain at least 3 characters")
        return value


class CampaignCaseFilterSuggestion(ReviewModel):
    value: str
    confidence: float
    matching_pool_cases_count: int


class CampaignCaseFilterCorrectionResponse(ReviewModel):
    typed_value: str
    suggestions: list[CampaignCaseFilterSuggestion]
    schema_version: Literal["campaign-case-filter-corrections/v1"] = (
        "campaign-case-filter-corrections/v1"
    )


class CampaignOverlapGroupCount(ReviewModel):
    group_id: str
    cases_count: int = Field(ge=0)


class CampaignOverlapOwner(ReviewModel):
    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    cases_count: int = Field(ge=0)
    group_counts: list[CampaignOverlapGroupCount] = Field(default_factory=list)


class CampaignAvailabilityRequest(ReviewModel):
    source_families: list[str] = Field(default_factory=list)
    group_ids: list[str] = Field(default_factory=list)
    requested_case_count: CaseCountInput = "all"
    synthesize_missing_values: bool = False
    case_filter: CampaignCaseFilter | None = None
    applied_filter_token: str | None = Field(default=None, max_length=4096)
    case_id_selection: CampaignCaseIdSelection | None = None
    applied_case_id_token: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def reject_multiple_case_selectors(self) -> CampaignAvailabilityRequest:
        if self.case_id_selection is not None and self.case_filter is not None:
            raise ValueError("case_filter and case_id_selection are mutually exclusive")
        return self


class CampaignAvailabilityResponse(ReviewModel):
    requested_case_count: int | None
    requested_field_scope: list[str]
    eligible_cases_count: int
    source_pool_cases_count: int = 0
    case_filter_matching_count: int = 0
    case_filter_excluded_count: int = 0
    projected_campaign_cases_count: int = 0
    eligible_review_units_count: int
    unavailable_cases_count: int
    unavailable_review_units_count: int
    fields_fully_exhausted: list[str]
    fields_partially_available: list[str]
    cases_available_for_all_selected_fields: int
    cases_available_for_some_selected_fields_only: int
    feasibility: FeasibilityStatus
    infeasible_message: str | None
    overlap_cases_count: int = 0
    overlap_group_counts: list[CampaignOverlapGroupCount] = Field(default_factory=list)
    overlap_campaigns: list[CampaignOverlapOwner] = Field(default_factory=list)
    unidentifiable_pool_units_count: int = 0
    identity_unavailable_cases_count: int = 0
    identity_conflict_cases_count: int = 0
    catalog_result_digest: str = "no_catalog"
    schema_version: Literal["campaign-availability/v1"] = "campaign-availability/v1"


class LoadPoolCasesRequest(ReviewModel):
    """Materialize (or top up) a draft campaign from the eligible pool."""

    requested_case_count: CaseCountInput = "all"
    confirm_smaller_count: bool = False
    confirm_remaining_fields_only: bool = False
    synthesize_missing_values: bool = False
    case_filter: CampaignCaseFilter | None = None
    applied_filter_token: str | None = Field(default=None, max_length=4096)
    case_id_selection: CampaignCaseIdSelection | None = None
    applied_case_id_token: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def reject_conflicting_missing_policies(self) -> LoadPoolCasesRequest:
        if self.confirm_remaining_fields_only and self.synthesize_missing_values:
            raise ValueError(
                "confirm_remaining_fields_only cannot be combined with synthesize_missing_values"
            )
        if self.case_id_selection is not None and self.case_filter is not None:
            raise ValueError("case_filter and case_id_selection are mutually exclusive")
        return self


class LoadPoolCasesResponse(ReviewModel):
    campaign_id: uuid.UUID
    availability: CampaignAvailabilityResponse
    materialized_cases: int
    materialized_units: int
    total_units: int
    not_ready_for_publish: bool
    schema_version: Literal["load-pool-cases/v1"] = "load-pool-cases/v1"


__all__ = [
    "CampaignCaseFilter",
    "CampaignCaseFilterApplyRequest",
    "CampaignCaseFilterApplyResponse",
    "CampaignCaseIdApplyRequest",
    "CampaignCaseIdApplyResponse",
    "CampaignCaseIdSelection",
    "CampaignCaseFilterClause",
    "CampaignCaseFilterCorrectionRequest",
    "CampaignCaseFilterCorrectionResponse",
    "CampaignCaseFilterExportRequest",
    "CampaignCaseFilterSuggestion",
    "CampaignJudgmentYearRange",
    "CampaignJudgmentYearValue",
    "CampaignOverlapGroupCount",
    "CampaignOverlapOwner",
    "CampaignAvailabilityRequest",
    "CampaignAvailabilityResponse",
    "CaseCountInput",
    "FeasibilityStatus",
    "LoadPoolCasesRequest",
    "LoadPoolCasesResponse",
]
