"""Deterministic overlap, workload, and coverage math for the allocation planner.

Pure functions over planner value types: no storage, randomness, or I/O. The planner in
:mod:`review_platform.review.allocation` composes these to size and summarise an allocation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations

from review_platform.review.allocation.types import (
    AllocationPolicy,
    AllocationPreview,
    AllocationSubject,
    FeasibilityResult,
    PlannedAssignment,
    ReviewerWorkloadSummary,
    SelectionLayer,
    SubjectCoverageSummary,
)


def required_totals(reviewer_count: int, policy: AllocationPolicy) -> dict[str, int | float]:
    pair_count = pairwise_count(reviewer_count)
    pair_specific_overlap = policy.target_pairwise_overlap - policy.target_global_overlap
    global_assignment_count = reviewer_count * policy.target_global_overlap
    pair_assignment_count = max(pair_specific_overlap, 0) * pair_count * 2
    overlap_assignment_count = global_assignment_count + pair_assignment_count
    uniform_reviews_per_subject = max(policy.uniform_reviews_per_subject, 1)

    if uniform_reviews_per_subject == 1:
        # Original sampling semantics: the "unique" layer's size is driven by the reviewer
        # workload budget left over after the hub/pairwise layers, and each unique subject gets
        # exactly one reviewer, so assignment count and subject count coincide.
        target_total_assignments = reviewer_count * policy.target_per_reviewer_workload
        unique_assignment_count = target_total_assignments - overlap_assignment_count
        unique_subject_count = max(unique_assignment_count, 0)
    else:
        # Uniform-coverage mode (campaign case review): every remaining subject needs exactly
        # ``uniform_reviews_per_subject`` distinct reviewers. Size the unique layer directly off
        # the requested subject count, not the workload budget -- ``target_per_reviewer_workload``
        # is a display estimate here, not a coverage constraint, so it must not gate how many
        # subjects can be covered (the source of the false-infeasible bug: a workload-derived
        # subject count doesn't match "every case reviewed N times").
        global_subject_count = policy.target_global_overlap
        pair_subject_count = max(pair_specific_overlap, 0) * pair_count
        unique_subject_count = max(
            policy.target_distinct_subjects - global_subject_count - pair_subject_count, 0
        )
        unique_assignment_count = unique_subject_count * uniform_reviews_per_subject
        target_total_assignments = overlap_assignment_count + unique_assignment_count

    required_distinct_subjects = (
        policy.target_global_overlap
        + max(pair_specific_overlap, 0) * pair_count
        + unique_subject_count
    )
    coverage_ratio = (
        required_distinct_subjects / policy.target_distinct_subjects
        if policy.target_distinct_subjects
        else 0.0
    )
    overlap_ratio = (
        (target_total_assignments - unique_assignment_count) / target_total_assignments
        if target_total_assignments
        else 0.0
    )
    return {
        "reviewer_count": reviewer_count,
        "pair_count": pair_count,
        "target_total_assignments": target_total_assignments,
        "global_assignment_count": global_assignment_count,
        "pair_specific_overlap": pair_specific_overlap,
        "pair_assignment_count": pair_assignment_count,
        "overlap_assignment_count": overlap_assignment_count,
        "unique_assignment_count": unique_assignment_count,
        "unique_subject_count": unique_subject_count,
        "required_distinct_subjects": required_distinct_subjects,
        "coverage_ratio": round(coverage_ratio, 4),
        "overlap_ratio": round(overlap_ratio, 4),
    }


def pairwise_count(reviewer_count: int) -> int:
    return reviewer_count * (reviewer_count - 1) // 2


def window_index(pair_index: int, local_index: int, policy: AllocationPolicy) -> int | None:
    if policy.rolling_window_size <= 0:
        return None
    stride = max(policy.rolling_window_stride, 1)
    return pair_index + (local_index // max(policy.rolling_window_size, 1)) * stride


def metric_normalizers(
    subjects: tuple[AllocationSubject, ...], metric_names: Iterable[str]
) -> dict[str, float]:
    normalizers: dict[str, float] = {}
    for metric_name in metric_names:
        maximum = max(
            (float(subject.metrics.get(metric_name, 0.0)) for subject in subjects), default=0.0
        )
        normalizers[metric_name] = maximum if maximum > 0 else 1.0
    return normalizers


def hub_score(
    subject: AllocationSubject, policy: AllocationPolicy, normalizers: dict[str, float]
) -> float:
    score = 0.0
    for metric_name, weight in policy.metric_weights.items():
        score += weight * (float(subject.metrics.get(metric_name, 0.0)) / normalizers[metric_name])
    return score


def summarize(
    *,
    assignments: tuple[PlannedAssignment, ...],
    reviewer_ids: tuple[str, ...],
    eligible_count: int,
    target_distinct: int,
    global_overlap: int,
) -> AllocationPreview:
    by_subject: dict[str, set[str]] = defaultdict(set)
    layer_by_subject: dict[str, SelectionLayer] = {}
    for assignment in assignments:
        by_subject[assignment.subject_id].add(assignment.reviewer_id)
        layer_by_subject.setdefault(assignment.subject_id, assignment.selection_layer)

    pairwise_matrix: dict[str, dict[str, int]] = {reviewer_id: {} for reviewer_id in reviewer_ids}
    for left, right in combinations(reviewer_ids, 2):
        pairwise_matrix[left][right] = sum(
            {left, right}.issubset(reviewers) for reviewers in by_subject.values()
        )

    workload_summaries: list[ReviewerWorkloadSummary] = []
    for reviewer_id in reviewer_ids:
        reviewer_assignments = [
            assignment for assignment in assignments if assignment.reviewer_id == reviewer_id
        ]
        workload_summaries.append(
            ReviewerWorkloadSummary(
                reviewer_id=reviewer_id,
                planned_assignment_count=len(reviewer_assignments),
                unique_assignment_count=sum(
                    assignment.selection_layer == "unique" for assignment in reviewer_assignments
                ),
                pairwise_overlap_count=sum(
                    assignment.selection_layer in {"pairwise", "rolling"}
                    for assignment in reviewer_assignments
                ),
                global_overlap_count=sum(
                    assignment.selection_layer == "global_hub"
                    for assignment in reviewer_assignments
                ),
            )
        )

    assigned_distinct = len(by_subject)
    expected_total_assignments = len(assignments)
    unique_assignments = sum(len(reviewers) == 1 for reviewers in by_subject.values())
    coverage = SubjectCoverageSummary(
        total_eligible_subjects=eligible_count,
        total_distinct_subjects=target_distinct,
        assigned_distinct_subjects=assigned_distinct,
        unassigned_eligible_count=max(eligible_count - assigned_distinct, 0),
        hub_subject_count=global_overlap,
        random_subject_count=max(assigned_distinct - global_overlap, 0),
        expected_total_assignments=expected_total_assignments,
        coverage_ratio=round(assigned_distinct / target_distinct, 4) if target_distinct else 0.0,
        overlap_ratio=round(
            (expected_total_assignments - unique_assignments) / expected_total_assignments,
            4,
        )
        if expected_total_assignments
        else 0.0,
    )
    return AllocationPreview(
        feasibility=FeasibilityResult(status="feasible"),
        assignments=assignments,
        reviewer_workloads=tuple(workload_summaries),
        pairwise_overlap_matrix=pairwise_matrix,
        subject_coverage=coverage,
    )
