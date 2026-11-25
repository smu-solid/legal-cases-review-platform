from __future__ import annotations

from collections import Counter

import pytest

from review_platform.review.allocation import (
    AllocationPlanner,
    AllocationPolicy,
    AllocationReviewer,
    AllocationSubject,
)


def subjects(
    count: int, *, kind: str = "case", review_kind: str = "metadata_field"
) -> list[AllocationSubject]:
    return [
        AllocationSubject(
            subject_id=f"subject-{index:04d}",
            subject_kind=kind,
            review_kind=review_kind,
            metrics={
                "incoming_citation_count": float(count - index),
                "validator_disagreement_count": float(index % 7),
                "provenance_risk": float(index % 3),
            },
        )
        for index in range(count)
    ]


def reviewers(count: int) -> list[AllocationReviewer]:
    return [AllocationReviewer(reviewer_id=f"R{index}") for index in range(1, count + 1)]


def policy(**overrides: object) -> AllocationPolicy:
    values: dict[str, object] = {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "target_distinct_subjects": 60,
        "target_per_reviewer_workload": 25,
        "target_pairwise_overlap": 10,
        "target_global_overlap": 4,
        "rolling_window_size": 3,
        "rolling_window_stride": 2,
        "hub_priority_count": 8,
        "random_seed": "seed-a",
        "allocation_policy_version": "reviewer-allocation/v1",
        "metric_weights": {
            "incoming_citation_count": 0.6,
            "validator_disagreement_count": 0.25,
            "provenance_risk": 0.15,
        },
    }
    values.update(overrides)
    return AllocationPolicy(**values)  # type: ignore[arg-type]


def test_planner_is_deterministic_with_fixed_seed() -> None:
    planner = AllocationPlanner()
    first = planner.plan(subjects=subjects(80), reviewers=reviewers(4), policy=policy())
    second = planner.plan(subjects=subjects(80), reviewers=reviewers(4), policy=policy())

    assert first.feasibility.status == "feasible_with_warnings"
    assert first.assignments == second.assignments
    assert first.pairwise_overlap_matrix == second.pairwise_overlap_matrix
    assert first.subject_coverage is not None
    assert first.subject_coverage.expected_total_assignments == 100


def test_different_seed_changes_non_hub_selection() -> None:
    planner = AllocationPlanner()
    first = planner.plan(
        subjects=subjects(90), reviewers=reviewers(4), policy=policy(random_seed="seed-a")
    )
    second = planner.plan(
        subjects=subjects(90), reviewers=reviewers(4), policy=policy(random_seed="seed-b")
    )

    first_global = {
        assignment.subject_id
        for assignment in first.assignments
        if assignment.selection_layer == "global_hub"
    }
    second_global = {
        assignment.subject_id
        for assignment in second.assignments
        if assignment.selection_layer == "global_hub"
    }
    first_non_hub = {
        assignment.subject_id
        for assignment in first.assignments
        if assignment.selection_layer != "global_hub"
    }
    second_non_hub = {
        assignment.subject_id
        for assignment in second.assignments
        if assignment.selection_layer != "global_hub"
    }
    assert first_global == second_global
    assert first_non_hub != second_non_hub


def test_pairwise_global_and_rolling_overlap_targets_are_met() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(80), reviewers=reviewers(4), policy=policy()
    )

    assert preview.feasibility.status == "feasible_with_warnings"
    for left, row in preview.pairwise_overlap_matrix.items():
        for right, count in row.items():
            if left != right:
                assert count == 10
    global_assignments = [
        assignment
        for assignment in preview.assignments
        if assignment.selection_layer == "global_hub"
    ]
    assert len({assignment.subject_id for assignment in global_assignments}) == 4
    assert all(
        assignment.window_index is not None
        for assignment in preview.assignments
        if assignment.selection_layer == "rolling"
    )


def test_infeasible_plan_reports_workload_overlap_arithmetic() -> None:
    impossible = policy(
        target_distinct_subjects=500,
        target_per_reviewer_workload=275,
        target_pairwise_overlap=75,
        target_global_overlap=25,
        hub_priority_count=25,
    )
    preview = AllocationPlanner().plan(
        subjects=subjects(800), reviewers=reviewers(4), policy=impossible
    )

    assert preview.feasibility.status == "infeasible"
    assert {error.code for error in preview.feasibility.errors} == {
        "distinct_pool_too_small_for_workload"
    }
    assert preview.feasibility.computed_totals["required_distinct_subjects"] == 725
    assert preview.assignments == ()


def test_reviewer_pool_and_subject_pool_blockers_are_structured() -> None:
    inactive_preview = AllocationPlanner().plan(
        subjects=subjects(80),
        reviewers=[AllocationReviewer("R1"), AllocationReviewer("R2", active=False)],
        policy=policy(),
    )
    assert inactive_preview.feasibility.status == "blocked_by_reviewer_pool"
    assert "blocked_by_reviewer_pool" in {
        error.code for error in inactive_preview.feasibility.errors
    }

    small_preview = AllocationPlanner().plan(
        subjects=subjects(10), reviewers=reviewers(4), policy=policy()
    )
    assert small_preview.feasibility.status == "infeasible"
    assert "not_enough_eligible_subjects" in {
        error.code for error in small_preview.feasibility.errors
    }


def test_workload_balance_and_duplicate_assignment_invariants() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(80), reviewers=reviewers(4), policy=policy()
    )

    counts = [summary.planned_assignment_count for summary in preview.reviewer_workloads]
    assert counts == [25, 25, 25, 25]
    pairs = {(assignment.reviewer_id, assignment.subject_id) for assignment in preview.assignments}
    assert len(pairs) == len(preview.assignments)


def test_subject_kind_extensibility_is_not_case_only() -> None:
    statute_policy = policy(
        subject_kind="statute",
        review_kind="metadata_field",
        target_distinct_subjects=20,
        target_per_reviewer_workload=10,
        target_pairwise_overlap=4,
        target_global_overlap=2,
    )
    preview = AllocationPlanner().plan(
        subjects=subjects(40, kind="statute"),
        reviewers=reviewers(3),
        policy=statute_policy,
    )

    assert preview.feasibility.status == "feasible"
    assert preview.assignments


def test_reviewer_safe_projection_does_not_leak_overlap_or_peer_data() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(80), reviewers=reviewers(4), policy=policy()
    )
    safe = preview.reviewer_safe_assignments("R1")

    assert safe
    assert all(set(item) == {"subject_id"} for item in safe)
    assert not any(
        {"reviewer_id", "selection_layer", "overlap_group_key", "window_index"} & set(item)
        for item in safe
    )


def uniform_policy(cases: int, reviewer_count: int, minimum_reviews: int, **overrides: object):
    total_assignments = cases * minimum_reviews
    per_reviewer = -(-total_assignments // reviewer_count) if reviewer_count else 0
    values: dict[str, object] = {
        "subject_kind": "case",
        "review_kind": "metadata_field",
        "target_distinct_subjects": cases,
        "target_per_reviewer_workload": max(1, per_reviewer),
        "target_pairwise_overlap": 0,
        "target_global_overlap": 0,
        "rolling_window_size": 0,
        "rolling_window_stride": 1,
        "hub_priority_count": 0,
        "random_seed": "campaign-seed",
        "allocation_policy_version": "reviewer-allocation/v1",
        "metric_weights": {},
        "uniform_reviews_per_subject": minimum_reviews,
    }
    values.update(overrides)
    return AllocationPolicy(**values)  # type: ignore[arg-type]


def test_uniform_coverage_more_cases_than_reviewers_is_feasible() -> None:
    """The confirmed bug: 30 cases / 2 reviewers / minimum 2 must not be infeasible."""
    preview = AllocationPlanner().plan(
        subjects=subjects(30), reviewers=reviewers(2), policy=uniform_policy(30, 2, 2)
    )

    assert preview.feasibility.status in {"feasible", "feasible_with_warnings"}
    assert len(preview.assignments) == 60
    by_subject: dict[str, set[str]] = {}
    for assignment in preview.assignments:
        by_subject.setdefault(assignment.subject_id, set()).add(assignment.reviewer_id)
    assert len(by_subject) == 30
    assert all(len(reviewer_ids) == 2 for reviewer_ids in by_subject.values())


def test_uniform_coverage_extra_reviewers_still_covers_every_case() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(30), reviewers=reviewers(3), policy=uniform_policy(30, 3, 2)
    )

    assert preview.feasibility.status in {"feasible", "feasible_with_warnings"}
    assert len(preview.assignments) == 60
    by_subject: dict[str, set[str]] = {}
    for assignment in preview.assignments:
        by_subject.setdefault(assignment.subject_id, set()).add(assignment.reviewer_id)
    assert len(by_subject) == 30
    assert all(len(reviewer_ids) == 2 for reviewer_ids in by_subject.values())


def test_uniform_coverage_single_reviewer_is_infeasible() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(30), reviewers=reviewers(1), policy=uniform_policy(30, 1, 2)
    )

    assert preview.feasibility.status != "feasible"
    assert "not_enough_reviewers" in {error.code for error in preview.feasibility.errors}
    assert preview.assignments == ()


def test_uniform_coverage_reviewer_count_below_minimum_reports_specific_reason() -> None:
    """3 reviews/case with only 2 reviewers can never work (each case needs 2 *distinct*
    reviewers), independent of case count -- the pairwise/global engine had no way to
    express     this at all for N >= 3; confirms the fix covers minimums beyond 2, not just
    the reported bug."""
    preview = AllocationPlanner().plan(
        subjects=subjects(12), reviewers=reviewers(2), policy=uniform_policy(12, 2, 3)
    )

    assert preview.feasibility.status == "infeasible"
    assert {error.code for error in preview.feasibility.errors} == {
        "insufficient_reviewers_for_uniform_coverage"
    }
    assert preview.assignments == ()


def test_uniform_coverage_inactive_reviewers_are_excluded_and_reported() -> None:
    preview = AllocationPlanner().plan(
        subjects=subjects(30),
        reviewers=[AllocationReviewer("R1"), AllocationReviewer("R2", active=False)],
        policy=uniform_policy(30, 2, 2),
    )

    assert preview.feasibility.status == "blocked_by_reviewer_pool"
    assert "blocked_by_reviewer_pool" in {error.code for error in preview.feasibility.errors}
    assert preview.assignments == ()


def _coverage_and_pairs(preview):
    """Return ``(reviewers_per_subject, Counter_of_reviewer_pairs, Counter_of_workloads)``."""
    by_subject: dict[str, set[str]] = {}
    for assignment in preview.assignments:
        by_subject.setdefault(assignment.subject_id, set()).add(assignment.reviewer_id)
    pairs = Counter(tuple(sorted(ids)) for ids in by_subject.values())
    workloads = Counter(assignment.reviewer_id for assignment in preview.assignments)
    return by_subject, pairs, workloads


def test_uniform_coverage_spreads_overlap_across_every_reviewer_pair() -> None:
    """Every case gets exactly N reviewers, and no single reviewer PAIR carries the campaign.

    Exact coverage alone is not enough for an agreement study: if the same two reviewers were
    paired on every case, the campaign would measure one pair's agreement repeatedly instead of
    the pool's. Guards that the pairing stays spread -- every possible pair is used, and used a
    comparable number of times -- for the reviewer counts a real campaign uses.
    """

    for reviewer_count in (3, 4, 5):
        preview = AllocationPlanner().plan(
            subjects=subjects(30),
            reviewers=reviewers(reviewer_count),
            policy=uniform_policy(30, reviewer_count, 2),
        )
        by_subject, pairs, workloads = _coverage_and_pairs(preview)

        assert len(by_subject) == 30
        assert all(len(ids) == 2 for ids in by_subject.values()), reviewer_count
        # Every distinct pair drawn from the pool is actually used...
        possible_pairs = reviewer_count * (reviewer_count - 1) // 2
        assert len(pairs) == possible_pairs, (reviewer_count, dict(pairs))
        # ...and none of them dominates: the most- and least-used pair differ by at most one case.
        assert max(pairs.values()) - min(pairs.values()) <= 1, (reviewer_count, dict(pairs))
        # Per-reviewer load stays even too, so "spread the pairs" is not achieved by overloading
        # one reviewer across many partners.
        assert max(workloads.values()) - min(workloads.values()) <= 1, (
            reviewer_count,
            dict(workloads),
        )


def test_uniform_coverage_never_assigns_one_reviewer_the_same_case_twice() -> None:
    """A case's N reviews must come from N *distinct* reviewers, never a repeat."""

    for reviewer_count in (2, 3, 6):
        for minimum_reviews in (2, 3):
            if reviewer_count < minimum_reviews:
                continue
            preview = AllocationPlanner().plan(
                subjects=subjects(24),
                reviewers=reviewers(reviewer_count),
                policy=uniform_policy(24, reviewer_count, minimum_reviews),
            )
            seen: Counter = Counter(
                (assignment.subject_id, assignment.reviewer_id)
                for assignment in preview.assignments
            )
            assert all(count == 1 for count in seen.values()), (reviewer_count, minimum_reviews)
            by_subject, _pairs, _workloads = _coverage_and_pairs(preview)
            assert all(len(ids) == minimum_reviews for ids in by_subject.values())


pytestmark = pytest.mark.no_db
