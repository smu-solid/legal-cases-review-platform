"""Admin request/response schemas for reviewer allocation runs.

These contracts are admin-only. They never echo peer reviewer identities, overlap-group
labels, pairwise/all-reviewer markers, or agreement status into reviewer-facing payloads;
the reviewer queue contracts in ``review.schemas`` remain allocation-blind."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

FeasibilityStatus = Literal[
    "feasible",
    "feasible_with_warnings",
    "infeasible",
    "blocked_by_snapshot_drift",
    "blocked_by_reviewer_pool",
]
SelectionLayer = Literal["global_hub", "pairwise", "rolling", "unique"]
RunStatus = Literal["previewed", "planned", "published", "discarded", "superseded"]

ReviewerId = Annotated[list[uuid.UUID], Field(min_length=2, max_length=50)]
Weight = Annotated[float, Field(ge=0.0, le=1.0)]


class AllocationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentCountsOut(AllocationModel):
    """One set of assignments counted at both granularities the platform actually uses.

    ``cases`` counts distinct ``(case, reviewer)`` pairs -- the *selection* granularity, because
    allocation is case-native: the planner assigns whole cases, and a reviewer never gets the same
    case twice (see ``AllocationServiceBase._case_key``).

    ``review_units`` counts ``(review unit, reviewer)`` pairs -- the *durable* granularity, one
    row per ``AssignmentPlan``/``Assignment``. Publishing fans each planned ``(case, reviewer)``
    out over every in-scope field/relation of that case, so ``review_units`` is normally the much
    larger number.

    Both are reported together, always, because the admin screen previously mixed them without
    saying which was which: the pre-publish panel showed the case count and the publish result
    showed the unit count, so the same campaign read as 8 in one place and 40 in another.
    """

    cases: int = Field(ge=0)
    review_units: int = Field(ge=0)


def counts_for_unit_pairs(
    pairs: list[tuple[uuid.UUID, uuid.UUID]], case_by_unit: dict[uuid.UUID, str]
) -> AssignmentCountsOut:
    """Count ``(reviewer_id, review_unit_id)`` pairs at both granularities.

    Used by the incremental path, which plans per review unit. A reviewer moving three
    fields of one case is three ``review_units`` but a single ``cases`` pair. Units
    missing from ``case_by_unit`` still count toward ``review_units``; they are keyed
    individually so they can never silently collapse into one another."""

    return AssignmentCountsOut(
        cases=len(
            {
                (reviewer_id, case_by_unit.get(unit_id) or f"unit:{unit_id}")
                for reviewer_id, unit_id in pairs
            }
        ),
        review_units=len(pairs),
    )


class AllocationPolicyInput(AllocationModel):
    """Allocation policy parameters shared by preview and persist requests."""

    subject_kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    review_kind: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    reviewer_ids: ReviewerId
    target_distinct_subjects: int = Field(ge=1, le=100_000)
    target_per_reviewer_workload: int = Field(ge=1, le=100_000)
    target_pairwise_overlap: int = Field(ge=0, le=100_000)
    target_global_overlap: int = Field(ge=0, le=100_000)
    rolling_window_size: int = Field(ge=0, le=100_000)
    rolling_window_stride: int = Field(ge=0, le=100_000)
    hub_priority_count: int = Field(ge=0, le=100_000)
    random_seed: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    allocation_policy_version: str = Field(min_length=1, max_length=80)
    metric_weights: dict[str, Weight] = Field(default_factory=dict, max_length=32)
    # Distinct reviewers required per "unique"-layer subject (see AllocationPolicy). Campaign case
    # review sends minimum_reviews_per_case here with target_pairwise_overlap/target_global_overlap
    # left at 0 -- the hub/pairwise layers target a different concept (subjects shared by a
    # specific reviewer pair or the whole pool), not "every case reviewed N times".
    uniform_reviews_per_subject: int = Field(default=1, ge=1, le=100)


CaseSelectionStrategy = Literal[
    "sequential",
    "random",
    "citation_in_hub",
    "citation_out_hub",
]


class SubjectPoolPreviewRequest(AllocationModel):
    subject_kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    review_kind: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    limit: int = Field(default=20, ge=1, le=100)
    selection_strategy: CaseSelectionStrategy = "sequential"
    random_seed: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$"
    )


class SubjectPoolSample(AllocationModel):
    review_subject_id: uuid.UUID
    subject_kind: str
    review_kind: str
    display_title: str
    selection_rank: int
    inbound_citation_count: int | None = None
    outbound_citation_count: int | None = None


class SubjectPoolPreviewResponse(AllocationModel):
    subject_kind: str
    review_kind: str
    eligible_subject_count: int
    pool_digest: str
    selection_strategy: CaseSelectionStrategy
    # ``False`` for a hub strategy when no eligible subject carries the citation-metric namespace;
    # the sample order then falls back to sequential and ``diagnostic`` explains why.
    metrics_available: bool
    diagnostic: str | None = None
    samples: list[SubjectPoolSample]


class FeasibilityIssueOut(AllocationModel):
    code: str
    message: str


class FeasibilityOut(AllocationModel):
    status: FeasibilityStatus
    errors: list[FeasibilityIssueOut]
    warnings: list[FeasibilityIssueOut]
    computed_totals: dict[str, float]
    suggested_adjustments: list[str]


class ReviewerWorkloadOut(AllocationModel):
    reviewer_id: uuid.UUID
    planned_assignment_count: int
    unique_assignment_count: int
    pairwise_overlap_count: int
    global_overlap_count: int


class SubjectCoverageOut(AllocationModel):
    total_eligible_subjects: int
    total_distinct_subjects: int
    assigned_distinct_subjects: int
    unassigned_eligible_count: int
    hub_subject_count: int
    random_subject_count: int
    expected_total_assignments: int
    coverage_ratio: float
    overlap_ratio: float


class AllocationPreviewResponse(AllocationModel):
    feasibility: FeasibilityOut
    pairwise_overlap_matrix: dict[str, dict[str, int]]
    reviewer_workloads: list[ReviewerWorkloadOut]
    subject_coverage: SubjectCoverageOut | None
    # The plan this preview would publish, at both granularities. ``reviewer_workloads`` and
    # ``subject_coverage`` are case-level here (an allocation subject IS a case on this path), so
    # without this the preview could not be compared with the unit-level publish result.
    planned_assignment_counts: AssignmentCountsOut
    pool_digest: str
    source_snapshot_digest: str
    allocation_policy_version: str
    planner_version: str
    schema_version: Literal["allocation-preview/v1"] = "allocation-preview/v1"


class AllocationRunResponse(AllocationModel):
    run_id: uuid.UUID
    campaign_id: uuid.UUID
    status: RunStatus
    feasibility_status: FeasibilityStatus
    allocation_policy_version: str
    planner_version: str
    source_snapshot_digest: str
    pool_digest: str
    planned_assignment_count: int
    distinct_subject_count: int
    reviewer_count: int
    created_at: datetime
    published_at: datetime | None
    lock_version: int
    replayed: bool = False
    schema_version: Literal["allocation-run/v1"] = "allocation-run/v1"


class AllocationRunPage(AllocationModel):
    items: list[AllocationRunResponse]
    next_cursor: str | None = None
    has_more: bool = False


class AllocationMatrixResponse(AllocationModel):
    run_id: uuid.UUID
    pairwise_overlap_matrix: dict[str, dict[str, int]]
    all_reviewer_overlap_count: int
    hub_subject_count: int


class ReviewerWorkloadsResponse(AllocationModel):
    run_id: uuid.UUID
    reviewer_workloads: list[ReviewerWorkloadOut]


class SubjectCoverageResponse(AllocationModel):
    run_id: uuid.UUID
    subject_coverage: SubjectCoverageOut


class AllocationPublishResponse(AllocationModel):
    run_id: uuid.UUID
    status: RunStatus
    # Retained as-is (review-unit level) for compatibility; ``published_assignment_counts`` is the
    # unambiguous form and carries the same number in ``review_units``.
    published_assignment_count: int
    created_assignment_count: int
    published_assignment_counts: AssignmentCountsOut
    published_at: datetime
    replayed: bool = False
    schema_version: Literal["allocation-publish/v1"] = "allocation-publish/v1"


class AllocationDiscardResponse(AllocationModel):
    run_id: uuid.UUID
    status: RunStatus
    replayed: bool = False


# ---------------------------------------------------------------------------
# Incremental allocation schemas (reviewer-pool change handling)
# ---------------------------------------------------------------------------

MovementClass = Literal["submitted", "claimed", "draft", "unclaimed"]
MovementKind = Literal["new", "moved", "preserved", "skipped"]
IncrementalFeasibilityStatus = Literal[
    "feasible",
    "feasible_with_warnings",
    "infeasible",
    "blocked_by_reviewer_pool",
    "blocked_by_capacity",
    "blocked_by_immutable_work",
]
AllocationMode = Literal["initial", "incremental"]

# Capacity weight biases the weighted-rendezvous ranking; a weight of 2.0 means roughly twice the
# share of a weight-1.0 reviewer. Distinct from ``Weight`` (a 0..1 metric coefficient).
CapacityWeight = Annotated[float, Field(gt=0.0, le=1000.0)]


class MovementPolicyInput(AllocationModel):
    allow_rebalance_unclaimed: bool = True
    allow_rebalance_claimed: bool = False
    allow_rebalance_draft: bool = False


class IncrementalPolicyInput(AllocationModel):
    """Admin request for an incremental allocation preview or persist."""

    subject_kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    review_kind: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    reviewer_ids: ReviewerId
    reviewer_capacity_weights: dict[str, CapacityWeight] = Field(
        default_factory=dict, max_length=50
    )
    min_reviews_per_subject: int = Field(default=2, ge=1, le=100)
    max_workload_per_reviewer: int | None = Field(default=None, ge=1, le=100_000)
    movement_policy: MovementPolicyInput = Field(default_factory=MovementPolicyInput)
    random_seed: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    allocation_policy_version: str = Field(min_length=1, max_length=80)
    base_run_id: uuid.UUID


class IncrementalFeasibilityIssueOut(AllocationModel):
    code: str
    message: str


class IncrementalFeasibilityOut(AllocationModel):
    status: IncrementalFeasibilityStatus
    errors: list[IncrementalFeasibilityIssueOut]
    warnings: list[IncrementalFeasibilityIssueOut]


class WorkloadSummaryOut(AllocationModel):
    reviewer_id: uuid.UUID
    count_before: int
    count_after: int


class MovementEntryOut(AllocationModel):
    subject_id: uuid.UUID
    from_reviewer_id: uuid.UUID | None
    to_reviewer_id: uuid.UUID
    movement_kind: MovementKind
    movement_reason: str


class IncrementalPreviewResponse(AllocationModel):
    """Admin-only incremental preview. Never returned to ordinary reviewers."""

    campaign_id: uuid.UUID
    base_run_id: uuid.UUID
    policy_version: str
    reviewer_pool_before: list[uuid.UUID]
    reviewer_pool_after: list[uuid.UUID]
    subject_count: int
    min_reviews_per_subject: int
    coverage_gap_count: int
    # Review-unit level (an incremental allocation subject IS a review unit on this path -- see
    # ``AllocationIncrementalInputsMixin``). The ``*_counts`` fields restate them alongside the
    # case-level equivalent so preview and publish speak the same two numbers as the initial path.
    new_assignment_count: int
    moved_assignment_count: int
    preserved_assignment_count: int
    new_assignment_counts: AssignmentCountsOut
    moved_assignment_counts: AssignmentCountsOut
    unassigned_subject_count: int
    workload_summaries: list[WorkloadSummaryOut]
    movement_plan: list[MovementEntryOut]
    feasibility: IncrementalFeasibilityOut
    schema_version: Literal["incremental-preview/v1"] = "incremental-preview/v1"


class IncrementalRunResponse(AllocationModel):
    run_id: uuid.UUID
    campaign_id: uuid.UUID
    base_run_id: uuid.UUID | None
    status: RunStatus
    allocation_mode: AllocationMode
    feasibility_status: IncrementalFeasibilityStatus
    allocation_policy_version: str
    planner_version: str
    new_assignment_count: int
    moved_assignment_count: int
    preserved_assignment_count: int
    created_at: datetime
    published_at: datetime | None
    lock_version: int
    replayed: bool = False
    schema_version: Literal["incremental-run/v1"] = "incremental-run/v1"


class IncrementalPublishResponse(AllocationModel):
    run_id: uuid.UUID
    status: RunStatus
    published_assignment_count: int
    new_assignment_count: int
    moved_assignment_count: int
    new_assignment_counts: AssignmentCountsOut
    moved_assignment_counts: AssignmentCountsOut
    # Reviewers this run moved untouched work away from who ended the publish with zero live
    # (non-released) assignments in the campaign -- they lost queue access to it. Empty unless a
    # reviewer was removed from the roster and had nothing left after the swap.
    revoked_reviewer_ids: list[uuid.UUID] = []
    published_at: datetime
    replayed: bool = False
    schema_version: Literal["incremental-publish/v1"] = "incremental-publish/v1"
