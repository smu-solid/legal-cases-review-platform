"""Value types for the deterministic reviewer allocation planner.

These frozen dataclasses are the planner's input/output contract. They carry no persistence or
storage concern; the planner in :mod:`review_platform.review.allocation` consumes and returns them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FeasibilityStatus = Literal[
    "feasible",
    "feasible_with_warnings",
    "infeasible",
    "blocked_by_snapshot_drift",
    "blocked_by_reviewer_pool",
]
SelectionLayer = Literal["global_hub", "pairwise", "rolling", "unique"]
PLANNER_VERSION = "allocation-planner/v1"


@dataclass(frozen=True, slots=True)
class AllocationSubject:
    subject_id: str
    subject_kind: str
    review_kind: str
    metrics: dict[str, float] = field(default_factory=dict)
    eligible: bool = True


@dataclass(frozen=True, slots=True)
class AllocationReviewer:
    reviewer_id: str
    active: bool = True
    authorized: bool = True
    workload_limit: int | None = None


@dataclass(frozen=True, slots=True)
class AllocationPolicy:
    subject_kind: str
    review_kind: str
    target_distinct_subjects: int
    target_per_reviewer_workload: int
    target_pairwise_overlap: int
    target_global_overlap: int
    rolling_window_size: int
    rolling_window_stride: int
    hub_priority_count: int
    random_seed: str
    allocation_policy_version: str
    metric_weights: dict[str, float] = field(default_factory=dict)
    planner_version: str = PLANNER_VERSION
    workload_imbalance_tolerance: int = 1
    # Distinct reviewers required per "unique"-layer subject. Defaults to 1 (the original
    # single-reviewer-per-subject sampling semantics, unchanged). Campaign case-review policies
    # set this to minimum_reviews_per_case (>1) so every subject gets that many distinct reviews
    # from the whole pool -- not the global/pairwise hub-sampling layers, which target a *subset*
    # of subjects shared by specific reviewer pairs and mean something different.
    uniform_reviews_per_subject: int = 1


@dataclass(frozen=True, slots=True)
class FeasibilityIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    status: FeasibilityStatus
    errors: tuple[FeasibilityIssue, ...] = ()
    warnings: tuple[FeasibilityIssue, ...] = ()
    computed_totals: dict[str, int | float] = field(default_factory=dict)
    suggested_adjustments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedAssignment:
    subject_id: str
    reviewer_id: str
    selection_layer: SelectionLayer
    overlap_group_key: str | None
    window_index: int | None

    def reviewer_projection(self) -> dict[str, str]:
        """Return the only safe reviewer-facing projection for an allocated subject."""

        return {"subject_id": self.subject_id}


@dataclass(frozen=True, slots=True)
class ReviewerWorkloadSummary:
    reviewer_id: str
    planned_assignment_count: int
    unique_assignment_count: int
    pairwise_overlap_count: int
    global_overlap_count: int


@dataclass(frozen=True, slots=True)
class SubjectCoverageSummary:
    total_eligible_subjects: int
    total_distinct_subjects: int
    assigned_distinct_subjects: int
    unassigned_eligible_count: int
    hub_subject_count: int
    random_subject_count: int
    expected_total_assignments: int
    coverage_ratio: float
    overlap_ratio: float


@dataclass(frozen=True, slots=True)
class AllocationPreview:
    feasibility: FeasibilityResult
    assignments: tuple[PlannedAssignment, ...] = ()
    reviewer_workloads: tuple[ReviewerWorkloadSummary, ...] = ()
    pairwise_overlap_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    subject_coverage: SubjectCoverageSummary | None = None

    def reviewer_safe_assignments(self, reviewer_id: str) -> tuple[dict[str, str], ...]:
        return tuple(
            assignment.reviewer_projection()
            for assignment in self.assignments
            if assignment.reviewer_id == reviewer_id
        )
