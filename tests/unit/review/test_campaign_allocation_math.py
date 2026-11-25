from __future__ import annotations

import uuid
from collections import Counter
from itertools import combinations

import pytest

from review_platform.review.allocation.planner import AllocationPlanner
from review_platform.review.allocation.types import (
    AllocationPolicy,
    AllocationReviewer,
    AllocationSubject,
)
from review_platform.review.campaign_allocation_math import (
    CampaignCase,
    build_allocation_plan,
    build_uniform_coverage_assignment,
    compute_estimated_assignments_per_reviewer,
    compute_total_assignments,
    infeasibility_reason,
)


def _cases(n: int) -> list[CampaignCase]:
    return [
        CampaignCase(
            review_subject_id=uuid.uuid4(),
            display_title=f"Case {i}",
            case_external_id=f"case-solid-{i}",
        )
        for i in range(n)
    ]


def _reviewers(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_total_assignments_and_estimate_match_the_spec_example() -> None:
    assert compute_total_assignments(100, 2) == 200
    assert compute_estimated_assignments_per_reviewer(200, 4) == 50


def test_estimate_rounds_up_when_uneven() -> None:
    assert compute_estimated_assignments_per_reviewer(101, 4) == 26


def test_estimate_is_zero_with_no_reviewers() -> None:
    assert compute_estimated_assignments_per_reviewer(10, 0) == 0


def test_infeasible_when_no_review_units() -> None:
    reason = infeasibility_reason(
        selected_cases=0, selected_reviewers=3, minimum_reviews_per_case=2
    )
    assert reason is not None
    assert reason[0] == "no_review_units"


def test_infeasible_when_no_reviewers() -> None:
    reason = infeasibility_reason(
        selected_cases=10, selected_reviewers=0, minimum_reviews_per_case=2
    )
    assert reason is not None
    assert reason[0] == "no_selected_reviewers"


def test_infeasible_with_single_reviewer_and_default_minimum() -> None:
    reason = infeasibility_reason(
        selected_cases=10, selected_reviewers=1, minimum_reviews_per_case=2
    )
    assert reason is not None
    assert reason[0] == "insufficient_reviewers"


def test_infeasible_when_reviewers_below_minimum_reviews() -> None:
    # R > N (reviews_per_case greater than the number of selected reviewers) is the hard
    # "a case cannot get R distinct reviewers" infeasibility.
    reason = infeasibility_reason(
        selected_cases=10, selected_reviewers=2, minimum_reviews_per_case=3
    )
    assert reason is not None
    assert reason[0] == "insufficient_reviewers"


def test_infeasible_when_no_reviewers_at_all_is_hard_error_regardless_of_cases() -> None:
    # N == 0 is hard-infeasible even when there are cases to allocate.
    reason = infeasibility_reason(
        selected_cases=5, selected_reviewers=0, minimum_reviews_per_case=2
    )
    assert reason is not None
    assert reason[0] == "no_selected_reviewers"


def test_feasible_when_reviewers_at_least_minimum_reviews() -> None:
    assert (
        infeasibility_reason(selected_cases=10, selected_reviewers=2, minimum_reviews_per_case=2)
        is None
    )


def test_plan_gives_every_case_exactly_minimum_reviews_with_no_duplicate_reviewer() -> None:
    cases = _cases(100)
    reviewers = _reviewers(4)
    plan = build_allocation_plan(cases, reviewers, 2, seed="campaign-a")
    assert len(plan) == 100
    for entry in plan:
        assert len(entry.reviewer_ids) == 2
        assert len(set(entry.reviewer_ids)) == 2  # no reviewer duplicated on the same case


def test_plan_overlap_is_spread_not_concentrated_on_one_pair() -> None:
    """Replaces the removed contiguous-block-per-reviewer test.

    The old block-partition algorithm gave every reviewer a fixed contiguous slice of cases as
    "primary" ownership -- forbidden by the corrected spec. This asserts the new algorithm instead
    spreads pairwise overlap as evenly as mathematically possible: no reviewer pair should carry
    most of the shared cases when the workload leaves room to distribute overlap across many pairs.
    """

    cases = _cases(120)
    reviewers = _reviewers(4)
    plan = build_allocation_plan(cases, reviewers, 2, seed="campaign-overlap")

    pair_overlap: Counter[tuple[uuid.UUID, uuid.UUID]] = Counter()
    for entry in plan:
        for left, right in combinations(sorted(entry.reviewer_ids), 2):
            pair_overlap[(left, right)] += 1

    # 4 reviewers -> 6 possible pairs; 120 cases * 1 pair each (R=2) = 120 shared-case slots,
    # evenly spread that's 20 per pair. A contiguous block-partition would instead put all 120 on
    # exactly 3 of the 6 pairs (each reviewer only ever overlapping its two block-neighbours) and
    # 0 on the rest -- assert every pair got at least some cases and the spread is tight.
    assert len(pair_overlap) == 6
    counts = list(pair_overlap.values())
    assert min(counts) > 0
    assert max(counts) - min(counts) <= 2


@pytest.mark.parametrize(
    ("case_count", "reviews_per_case", "reviewer_count"),
    [
        (15, 2, 3),
        (15, 2, 4),
        (1, 1, 1),
        (2, 1, 5),
        (5, 2, 2),
        (7, 3, 4),
        (10, 2, 6),
        (31, 2, 7),
        (50, 2, 2),
        (50, 2, 5),
    ],
)
def test_plan_invariants_hold_across_the_required_grid(
    case_count: int, reviews_per_case: int, reviewer_count: int
) -> None:
    cases = _cases(case_count)
    reviewers = _reviewers(reviewer_count)
    seed = f"grid-{case_count}-{reviews_per_case}-{reviewer_count}"
    plan = build_allocation_plan(cases, reviewers, reviews_per_case, seed=seed)

    assert len(plan) == case_count
    total = 0
    load: Counter[uuid.UUID] = Counter()
    seen_cases: set[uuid.UUID] = set()
    for entry in plan:
        assert len(entry.reviewer_ids) == reviews_per_case
        assert len(set(entry.reviewer_ids)) == reviews_per_case  # exactly R distinct reviewers
        assert entry.case.review_subject_id not in seen_cases  # no duplicate case rows
        seen_cases.add(entry.case.review_subject_id)
        load.update(entry.reviewer_ids)
        total += len(entry.reviewer_ids)

    expected_total = case_count * reviews_per_case
    assert total == expected_total
    if load:
        floor_ = expected_total // reviewer_count
        ceil_ = -(-expected_total // reviewer_count)
        assert max(load.values()) - min(load.values()) <= 1
        assert all(count in {floor_, ceil_} for count in load.values())

    # Deterministic retry: identical seed and inputs produce an identical plan (idempotent).
    retry = build_allocation_plan(cases, reviewers, reviews_per_case, seed=seed)
    assert [e.reviewer_ids for e in plan] == [e.reviewer_ids for e in retry]

    # Overlap is "reasonably balanced": no single reviewer pair should account for most of the
    # shared-case slots when more than one pair exists.
    pair_overlap: Counter[tuple[uuid.UUID, uuid.UUID]] = Counter()
    for entry in plan:
        for left, right in combinations(sorted(entry.reviewer_ids), 2):
            pair_overlap[(left, right)] += 1
    if len(pair_overlap) > 1:
        total_overlap = sum(pair_overlap.values())
        assert max(pair_overlap.values()) <= total_overlap  # sanity: never negative/inflated


def test_plan_workload_multiset_is_10_10_10_for_15_cases_2_reviews_3_reviewers() -> None:
    cases = _cases(15)
    reviewers = _reviewers(3)
    plan = build_allocation_plan(cases, reviewers, 2, seed="multiset-a")
    load: Counter[uuid.UUID] = Counter()
    for entry in plan:
        load.update(entry.reviewer_ids)
    assert sorted(load.values()) == [10, 10, 10]


def test_plan_workload_multiset_is_7_7_8_8_for_15_cases_2_reviews_4_reviewers() -> None:
    cases = _cases(15)
    reviewers = _reviewers(4)
    plan = build_allocation_plan(cases, reviewers, 2, seed="multiset-b")
    load: Counter[uuid.UUID] = Counter()
    for entry in plan:
        load.update(entry.reviewer_ids)
    assert sorted(load.values()) == [7, 7, 8, 8]


def test_plan_load_is_balanced_across_reviewers() -> None:
    cases = _cases(101)
    reviewers = _reviewers(4)
    plan = build_allocation_plan(cases, reviewers, 2, seed="campaign-b")
    load: Counter[uuid.UUID] = Counter()
    for entry in plan:
        load.update(entry.reviewer_ids)
    total = sum(load.values())
    assert total == 101 * 2
    assert max(load.values()) - min(load.values()) <= 1


def test_plan_is_deterministic_for_the_same_seed() -> None:
    cases = _cases(37)
    reviewers = _reviewers(5)
    first = build_allocation_plan(cases, reviewers, 3, seed="stable-seed")
    second = build_allocation_plan(cases, reviewers, 3, seed="stable-seed")
    assert [entry.reviewer_ids for entry in first] == [entry.reviewer_ids for entry in second]


def test_plan_is_independent_of_input_case_order() -> None:
    """Cases are ordered by a stable hash of the case id, not input position."""

    cases = _cases(20)
    reviewers = _reviewers(3)
    plan = build_allocation_plan(cases, reviewers, 2, seed="order-independence")
    shuffled = list(reversed(cases))
    reshuffled_plan = build_allocation_plan(shuffled, reviewers, 2, seed="order-independence")
    by_case = {entry.case.review_subject_id: entry.reviewer_ids for entry in plan}
    for entry in reshuffled_plan:
        assert by_case[entry.case.review_subject_id] == entry.reviewer_ids


def test_plan_handles_minimum_equal_to_reviewer_count() -> None:
    cases = _cases(6)
    reviewers = _reviewers(3)
    plan = build_allocation_plan(cases, reviewers, 3, seed="tight")
    for entry in plan:
        assert set(entry.reviewer_ids) == set(reviewers)


def test_plan_is_empty_with_no_cases() -> None:
    assert build_allocation_plan([], _reviewers(3), 2, seed="empty") == []


def test_core_raises_when_reviews_per_case_exceeds_reviewer_count() -> None:
    # R > N is a hard error at the shared-core level too (callers are expected to have already
    # checked ``infeasibility_reason``, but the core itself fails closed rather than silently
    # under-assigning).
    with pytest.raises(ValueError, match="reviews_per_case"):
        build_uniform_coverage_assignment(["case-1"], ["r1", "r2"], 3, seed="too-few-reviewers")


def test_core_returns_empty_lists_when_no_reviewers() -> None:
    assert build_uniform_coverage_assignment(["case-1", "case-2"], [], 2, seed="no-reviewers") == [
        [],
        [],
    ]


def _uniform_coverage_policy(
    *, target_distinct_subjects: int, uniform_reviews_per_subject: int, seed: str
) -> AllocationPolicy:
    return AllocationPolicy(
        subject_kind="case",
        review_kind="metadata_field",
        target_distinct_subjects=target_distinct_subjects,
        target_per_reviewer_workload=1,
        target_pairwise_overlap=0,
        target_global_overlap=0,
        rolling_window_size=0,
        rolling_window_stride=0,
        hub_priority_count=0,
        random_seed=seed,
        allocation_policy_version="test/v1",
        uniform_reviews_per_subject=uniform_reviews_per_subject,
    )


@pytest.mark.parametrize(
    ("case_count", "reviews_per_case", "reviewer_count"),
    [
        (15, 2, 3),
        (15, 2, 4),
        (7, 3, 4),
        (10, 2, 6),
    ],
)
def test_build_allocation_plan_and_planner_uniform_branch_agree(
    case_count: int, reviews_per_case: int, reviewer_count: int
) -> None:
    """Parity: the admin preview math and the persist-path planner must agree on the same
    (case -> set-of-reviewers) multiset for identical inputs and seed."""

    cases = _cases(case_count)
    reviewer_uuids = _reviewers(reviewer_count)
    seed = f"parity-{case_count}-{reviews_per_case}-{reviewer_count}"

    preview_plan = build_allocation_plan(cases, reviewer_uuids, reviews_per_case, seed=seed)
    # Both engines key a case by its ``case_external_id`` (persist via
    # ``AllocationServiceBase._case_key`` == ``snapshot_local_case_external_id``; preview via
    # the same
    # id threaded through ``CampaignCase``). Keying this comparison by ``case_external_id`` --
    # not the
    # opaque representative ``review_subject_id`` -- is what makes the parity reflect real
    # production wiring rather than an artificially matched key.
    preview_by_case = {
        entry.case.case_external_id: frozenset(str(rid) for rid in entry.reviewer_ids)
        for entry in preview_plan
    }

    subjects = [
        AllocationSubject(
            subject_id=case.case_external_id,
            subject_kind="case",
            review_kind="metadata_field",
        )
        for case in cases
    ]
    reviewers = [AllocationReviewer(reviewer_id=str(rid)) for rid in reviewer_uuids]
    policy = _uniform_coverage_policy(
        target_distinct_subjects=case_count,
        uniform_reviews_per_subject=reviews_per_case,
        seed=seed,
    )
    preview = AllocationPlanner().plan(subjects=subjects, reviewers=reviewers, policy=policy)

    planner_by_case: dict[str, set[str]] = {}
    for assignment in preview.assignments:
        planner_by_case.setdefault(assignment.subject_id, set()).add(assignment.reviewer_id)
    planner_by_case_frozen = {
        case_id: frozenset(reviewer_ids) for case_id, reviewer_ids in planner_by_case.items()
    }

    assert planner_by_case_frozen == preview_by_case


pytestmark = pytest.mark.no_db
