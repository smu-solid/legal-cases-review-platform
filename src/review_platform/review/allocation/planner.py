"""Pure deterministic reviewer allocation planner.

The planner is deliberately storage-agnostic: it accepts eligible subjects, reviewers, and policy
inputs, then returns a preview. Persistence, admin APIs, and assignment publishing are handled by
the sibling ``service`` and orchestration modules.

Value types live in :mod:`review_platform.review.allocation.types` and the overlap/coverage math in
:mod:`review_platform.review.allocation.math`; both are re-exported from the package root for
backwards-compatible imports of ``review_platform.review.allocation``.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from itertools import combinations

from review_platform.review.allocation.math import (
    hub_score,
    metric_normalizers,
    pairwise_count,
    required_totals,
    summarize,
    window_index,
)
from review_platform.review.allocation.types import (
    PLANNER_VERSION,
    AllocationPolicy,
    AllocationPreview,
    AllocationReviewer,
    AllocationSubject,
    FeasibilityIssue,
    FeasibilityResult,
    FeasibilityStatus,
    PlannedAssignment,
    ReviewerWorkloadSummary,
    SelectionLayer,
    SubjectCoverageSummary,
)
from review_platform.review.campaign_allocation_math import build_uniform_coverage_assignment

__all__ = [
    "PLANNER_VERSION",
    "AllocationPlanner",
    "AllocationPolicy",
    "AllocationPreview",
    "AllocationReviewer",
    "AllocationSubject",
    "FeasibilityIssue",
    "FeasibilityResult",
    "FeasibilityStatus",
    "PlannedAssignment",
    "ReviewerWorkloadSummary",
    "SelectionLayer",
    "SubjectCoverageSummary",
]


class AllocationPlanner:
    def plan(
        self,
        *,
        subjects: Iterable[AllocationSubject],
        reviewers: Iterable[AllocationReviewer],
        policy: AllocationPolicy,
    ) -> AllocationPreview:
        subject_list = tuple(subjects)
        reviewer_list = tuple(reviewers)
        eligible_subjects = self._eligible_subjects(subject_list, policy)
        feasibility = self._validate_inputs(
            eligible_subjects=eligible_subjects,
            reviewers=reviewer_list,
            policy=policy,
        )
        if feasibility.status in {"infeasible", "blocked_by_reviewer_pool"}:
            return AllocationPreview(feasibility=feasibility)

        active_reviewers = tuple(
            reviewer for reviewer in reviewer_list if reviewer.active and reviewer.authorized
        )
        reviewer_ids = tuple(reviewer.reviewer_id for reviewer in active_reviewers)
        totals = required_totals(len(reviewer_ids), policy)
        assignments = self._build_assignments(
            eligible_subjects=eligible_subjects,
            reviewer_ids=reviewer_ids,
            policy=policy,
            required_distinct=int(totals["required_distinct_subjects"]),
            pair_specific_overlap=int(totals["pair_specific_overlap"]),
            unique_subject_count=int(totals["unique_subject_count"]),
        )
        preview = summarize(
            assignments=assignments,
            reviewer_ids=reviewer_ids,
            eligible_count=len(eligible_subjects),
            target_distinct=policy.target_distinct_subjects,
            global_overlap=policy.target_global_overlap,
        )
        final_feasibility = self._validate_output(preview, policy, feasibility)
        return AllocationPreview(
            feasibility=final_feasibility,
            assignments=assignments,
            reviewer_workloads=preview.reviewer_workloads,
            pairwise_overlap_matrix=preview.pairwise_overlap_matrix,
            subject_coverage=preview.subject_coverage,
        )

    @staticmethod
    def _eligible_subjects(
        subjects: Iterable[AllocationSubject], policy: AllocationPolicy
    ) -> tuple[AllocationSubject, ...]:
        return tuple(
            subject
            for subject in subjects
            if subject.eligible
            and subject.subject_kind == policy.subject_kind
            and subject.review_kind == policy.review_kind
        )

    def _validate_inputs(
        self,
        *,
        eligible_subjects: tuple[AllocationSubject, ...],
        reviewers: tuple[AllocationReviewer, ...],
        policy: AllocationPolicy,
    ) -> FeasibilityResult:
        errors: list[FeasibilityIssue] = []
        warnings: list[FeasibilityIssue] = []
        suggestions: list[str] = []
        active_reviewers = tuple(
            reviewer for reviewer in reviewers if reviewer.active and reviewer.authorized
        )
        reviewer_count = len(active_reviewers)
        totals = required_totals(reviewer_count, policy)

        if reviewer_count < 2:
            errors.append(
                FeasibilityIssue(
                    "not_enough_reviewers",
                    "At least two active authorized reviewers are required for overlap planning.",
                )
            )
        elif (
            policy.uniform_reviews_per_subject > 1
            and reviewer_count < policy.uniform_reviews_per_subject
        ):
            errors.append(
                FeasibilityIssue(
                    "insufficient_reviewers_for_uniform_coverage",
                    f"At least {policy.uniform_reviews_per_subject} active reviewers are required "
                    f"so every subject can reach {policy.uniform_reviews_per_subject} distinct "
                    "reviews.",
                )
            )
        inactive_count = len(reviewers) - reviewer_count
        if inactive_count:
            errors.append(
                FeasibilityIssue(
                    "blocked_by_reviewer_pool",
                    f"{inactive_count} reviewer(s) are inactive or unauthorized.",
                )
            )
        if len({reviewer.reviewer_id for reviewer in reviewers}) != len(reviewers):
            errors.append(
                FeasibilityIssue(
                    "duplicate_reviewers", "Reviewer IDs must be unique within a pool."
                )
            )
        if policy.target_pairwise_overlap < policy.target_global_overlap:
            errors.append(
                FeasibilityIssue(
                    "pairwise_overlap_less_than_global",
                    "Pairwise overlap must include at least the global overlap subjects.",
                )
            )
        if policy.target_global_overlap > policy.target_per_reviewer_workload:
            errors.append(
                FeasibilityIssue(
                    "global_overlap_exceeds_workload",
                    "Global overlap cannot exceed per-reviewer workload.",
                )
            )
        if totals["overlap_assignment_count"] > totals["target_total_assignments"]:
            errors.append(
                FeasibilityIssue(
                    "overlap_exceeds_workload",
                    "Requested global and pairwise overlap consume more assignments than the "
                    "reviewer workload.",
                )
            )
        if totals["required_distinct_subjects"] > policy.target_distinct_subjects:
            errors.append(
                FeasibilityIssue(
                    "distinct_pool_too_small_for_workload",
                    "Requested workload and overlap require "
                    f"{totals['required_distinct_subjects']} distinct subjects, "
                    f"but target_distinct_subjects is {policy.target_distinct_subjects}.",
                )
            )
            suggestions.append(
                "Increase target_distinct_subjects, increase overlap, or lower "
                "target_per_reviewer_workload."
            )
        if len(eligible_subjects) < totals["required_distinct_subjects"]:
            errors.append(
                FeasibilityIssue(
                    "not_enough_eligible_subjects",
                    f"{totals['required_distinct_subjects']} eligible subjects are required, "
                    f"but only {len(eligible_subjects)} are available.",
                )
            )
        for reviewer in active_reviewers:
            if (
                reviewer.workload_limit is not None
                and reviewer.workload_limit < policy.target_per_reviewer_workload
            ):
                errors.append(
                    FeasibilityIssue(
                        "reviewer_workload_limit",
                        f"Reviewer {reviewer.reviewer_id} has a workload limit below the target.",
                    )
                )
        if totals["required_distinct_subjects"] < policy.target_distinct_subjects:
            warnings.append(
                FeasibilityIssue(
                    "unassigned_remainder",
                    f"{policy.target_distinct_subjects - totals['required_distinct_subjects']} "
                    "target subjects would remain unassigned by this workload and overlap policy.",
                )
            )

        status: FeasibilityStatus
        if any(
            error.code in {"blocked_by_reviewer_pool", "not_enough_reviewers"} for error in errors
        ):
            status = "blocked_by_reviewer_pool"
        elif errors:
            status = "infeasible"
        elif warnings:
            status = "feasible_with_warnings"
        else:
            status = "feasible"
        return FeasibilityResult(
            status=status,
            errors=tuple(errors),
            warnings=tuple(warnings),
            computed_totals=totals,
            suggested_adjustments=tuple(suggestions),
        )

    def _build_assignments(
        self,
        *,
        eligible_subjects: tuple[AllocationSubject, ...],
        reviewer_ids: tuple[str, ...],
        policy: AllocationPolicy,
        required_distinct: int,
        pair_specific_overlap: int,
        unique_subject_count: int,
    ) -> tuple[PlannedAssignment, ...]:
        ranked = self._rank_subjects(eligible_subjects, policy)
        global_subjects = ranked[: policy.target_global_overlap]
        remaining = self._seeded_order(ranked[policy.target_global_overlap :], policy.random_seed)
        pair_count = pair_specific_overlap * pairwise_count(len(reviewer_ids))
        pair_subjects = remaining[:pair_count]
        unique_subjects = remaining[pair_count : pair_count + unique_subject_count]
        selected_count = len(global_subjects) + len(pair_subjects) + len(unique_subjects)
        if selected_count != required_distinct:
            raise RuntimeError("planner selected an unexpected number of distinct subjects")

        assignments: list[PlannedAssignment] = []
        for subject in global_subjects:
            assignments.extend(
                PlannedAssignment(
                    subject_id=subject.subject_id,
                    reviewer_id=reviewer_id,
                    selection_layer="global_hub",
                    overlap_group_key="global_hub",
                    window_index=None,
                )
                for reviewer_id in reviewer_ids
            )

        pairs = tuple(combinations(reviewer_ids, 2))
        cursor = 0
        for pair_index, pair in enumerate(pairs):
            for local_index in range(pair_specific_overlap):
                subject = pair_subjects[cursor]
                cursor += 1
                index = window_index(pair_index, local_index, policy)
                layer: SelectionLayer = "rolling" if policy.rolling_window_size > 0 else "pairwise"
                group_key = f"{pair[0]}:{pair[1]}"
                assignments.extend(
                    PlannedAssignment(
                        subject_id=subject.subject_id,
                        reviewer_id=reviewer_id,
                        selection_layer=layer,
                        overlap_group_key=group_key,
                        window_index=index,
                    )
                    for reviewer_id in pair
                )

        workload = Counter(assignment.reviewer_id for assignment in assignments)
        uniform_reviews_per_subject = max(policy.uniform_reviews_per_subject, 1)
        reviews_per_subject = min(uniform_reviews_per_subject, len(reviewer_ids))

        # Campaign case-review's uniform-coverage configuration (uniform_reviews_per_subject > 1,
        # no global/pairwise hub-sampling) delegates to the exact same pure core used by
        # ``campaign_allocation_math.build_allocation_plan`` -- the admin-facing preview -- so the
        # preview and the persisted plan agree (see that module's ``campaign_allocation_seed`` for
        # the matching seed unification). The single-reviewer-per-subject layered engine (the
        # original sampling semantics, ``uniform_reviews_per_subject == 1``) and any configuration
        # that also requests global/pairwise overlap are intentionally left on the original
        # workload-then-reviewer-id greedy pick below -- unchanged.
        use_shared_core = (
            uniform_reviews_per_subject > 1
            and policy.target_pairwise_overlap == 0
            and policy.target_global_overlap == 0
        )
        if use_shared_core and unique_subjects:
            per_subject_reviewers = build_uniform_coverage_assignment(
                [subject.subject_id for subject in unique_subjects],
                list(reviewer_ids),
                reviews_per_subject,
                seed=policy.random_seed,
                initial_workload=dict(workload),
            )
            for subject, chosen_reviewers in zip(
                unique_subjects, per_subject_reviewers, strict=True
            ):
                for reviewer_id in chosen_reviewers:
                    workload[reviewer_id] += 1
                assignments.extend(
                    PlannedAssignment(
                        subject_id=subject.subject_id,
                        reviewer_id=reviewer_id,
                        selection_layer="unique",
                        overlap_group_key=None,
                        window_index=None,
                    )
                    for reviewer_id in chosen_reviewers
                )
        else:
            for subject in unique_subjects:
                # Greedily pick the ``uniform_reviews_per_subject`` reviewers with the lowest
                # current workload for this subject (no repeats per subject), so coverage stays
                # load-balanced even when N > 1. Deterministic: ties break on reviewer id.
                chosen: list[str] = []
                for _ in range(reviews_per_subject):
                    candidate_id = min(
                        (rid for rid in reviewer_ids if rid not in chosen),
                        key=lambda candidate: (workload[candidate], candidate),
                    )
                    chosen.append(candidate_id)
                    workload[candidate_id] += 1
                assignments.extend(
                    PlannedAssignment(
                        subject_id=subject.subject_id,
                        reviewer_id=reviewer_id,
                        selection_layer="unique",
                        overlap_group_key=None,
                        window_index=None,
                    )
                    for reviewer_id in chosen
                )
        return tuple(assignments)

    def _rank_subjects(
        self, eligible_subjects: tuple[AllocationSubject, ...], policy: AllocationPolicy
    ) -> tuple[AllocationSubject, ...]:
        normalizers = metric_normalizers(eligible_subjects, policy.metric_weights.keys())
        return tuple(
            sorted(
                eligible_subjects,
                key=lambda subject: (
                    -hub_score(subject, policy, normalizers),
                    self._stable_random(subject.subject_id, policy.random_seed),
                    subject.subject_id,
                ),
            )
        )

    @staticmethod
    def _seeded_order(
        subjects: tuple[AllocationSubject, ...], random_seed: str
    ) -> tuple[AllocationSubject, ...]:
        return tuple(
            sorted(
                subjects,
                key=lambda subject: (
                    AllocationPlanner._stable_random(subject.subject_id, random_seed),
                    subject.subject_id,
                ),
            )
        )

    @staticmethod
    def _stable_random(subject_id: str, random_seed: str) -> float:
        digest = hashlib.sha256(f"{random_seed}:{subject_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    @staticmethod
    def _validate_output(
        preview: AllocationPreview, policy: AllocationPolicy, feasibility: FeasibilityResult
    ) -> FeasibilityResult:
        if not preview.reviewer_workloads:
            return feasibility
        counts = [summary.planned_assignment_count for summary in preview.reviewer_workloads]
        imbalance = max(counts) - min(counts)
        if imbalance > policy.workload_imbalance_tolerance:
            issue = FeasibilityIssue(
                "reviewer_workload_imbalance",
                f"Reviewer workload imbalance is {imbalance}, above tolerance.",
            )
            return FeasibilityResult(
                status="feasible_with_warnings",
                errors=feasibility.errors,
                warnings=feasibility.warnings + (issue,),
                computed_totals=feasibility.computed_totals,
                suggested_adjustments=feasibility.suggested_adjustments,
            )
        return feasibility
