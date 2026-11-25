"""Frozen input/output types for the pure incremental allocation planner.

Storage-agnostic value objects shared by the planner and the service layer. Kept separate so the
planner module holds only the algorithm. The planner module re-exports these for stable imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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

INCREMENTAL_PLANNER_VERSION = "incremental-planner/v1"


@dataclass(frozen=True, slots=True)
class ExistingAssignment:
    subject_id: str
    reviewer_id: str
    movement_class: MovementClass


@dataclass(frozen=True, slots=True)
class IncrementalReviewer:
    reviewer_id: str
    active: bool = True
    authorized: bool = True
    capacity_weight: float = 1.0
    workload_limit: int | None = None


@dataclass(frozen=True, slots=True)
class MovementPolicy:
    allow_rebalance_unclaimed: bool = True
    allow_rebalance_claimed: bool = False
    allow_rebalance_draft: bool = False


@dataclass(frozen=True, slots=True)
class IncrementalPolicy:
    min_reviews_per_subject: int
    max_workload_per_reviewer: int | None
    movement_policy: MovementPolicy
    random_seed: str
    allocation_policy_version: str


@dataclass(frozen=True, slots=True)
class MovementEntry:
    subject_id: str
    from_reviewer_id: str | None
    to_reviewer_id: str
    movement_kind: MovementKind
    movement_reason: str


@dataclass(frozen=True, slots=True)
class WorkloadSummary:
    reviewer_id: str
    count_before: int
    count_after: int


@dataclass(frozen=True, slots=True)
class IncrementalFeasibilityIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class IncrementalFeasibilityResult:
    status: IncrementalFeasibilityStatus
    errors: tuple[IncrementalFeasibilityIssue, ...] = ()
    warnings: tuple[IncrementalFeasibilityIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class IncrementalAllocationPreview:
    feasibility: IncrementalFeasibilityResult
    movement_plan: tuple[MovementEntry, ...]
    reviewer_pool_before: tuple[str, ...]
    reviewer_pool_after: tuple[str, ...]
    workload_summaries: tuple[WorkloadSummary, ...]
    coverage_before: dict[str, int]
    coverage_after: dict[str, int]
    new_assignment_count: int
    moved_assignment_count: int
    preserved_assignment_count: int
    unassigned_subject_ids: tuple[str, ...]
