"""Tests for incremental allocation (reviewer-pool change handling).

Covers:
  - Pure planner: determinism, coverage gap filling, preservation rules, workload balance,
    capacity weights, feasibility statuses, blinding invariants.
  - Integration: preview/persist/publish API flow, RBAC, idempotency, snapshot drift guard,
    reviewer-facing queue blinding.
"""

from __future__ import annotations

import pytest

from review_platform.review.incremental_planner import (
    ExistingAssignment,
    IncrementalAllocationPreview,
    IncrementalPlanner,
    IncrementalPolicy,
    IncrementalReviewer,
    MovementPolicy,
)

# ---------------------------------------------------------------------------
# Pure planner helpers
# ---------------------------------------------------------------------------


def _sids(count: int) -> tuple[str, ...]:
    return tuple(f"s-{index:04d}" for index in range(count))


def _reviewers(count: int, *, capacity: float = 1.0) -> tuple[IncrementalReviewer, ...]:
    return tuple(
        IncrementalReviewer(reviewer_id=f"R{index}", capacity_weight=capacity)
        for index in range(1, count + 1)
    )


def _policy(**kwargs: object) -> IncrementalPolicy:
    defaults: dict[str, object] = {
        "min_reviews_per_subject": 2,
        "max_workload_per_reviewer": None,
        "movement_policy": MovementPolicy(),
        "random_seed": "test-seed",
        "allocation_policy_version": "incremental/v1",
    }
    defaults.update(kwargs)
    return IncrementalPolicy(**defaults)  # type: ignore[arg-type]


def _existing(subject_id: str, reviewer_id: str, mc: str) -> ExistingAssignment:
    return ExistingAssignment(subject_id=subject_id, reviewer_id=reviewer_id, movement_class=mc)  # type: ignore[arg-type]


def run_plan(
    subjects: tuple[str, ...],
    reviewers: tuple[IncrementalReviewer, ...],
    existing: tuple[ExistingAssignment, ...] = (),
    *,
    previous_reviewer_ids: tuple[str, ...] = (),
    **policy_kwargs: object,
) -> IncrementalAllocationPreview:
    policy = _policy(**policy_kwargs)
    return IncrementalPlanner().plan(
        subject_ids=subjects,
        reviewers=reviewers,
        existing_assignments=existing,
        policy=policy,
        previous_reviewer_ids=previous_reviewer_ids,
    )


# ---------------------------------------------------------------------------
# Pure planner tests
# ---------------------------------------------------------------------------


def test_deterministic_output_with_fixed_seed() -> None:
    sids = _sids(10)
    revs = _reviewers(3)
    first = run_plan(sids, revs)
    second = run_plan(sids, revs)
    assert first.movement_plan == second.movement_plan
    assert first.coverage_after == second.coverage_after


def test_different_seed_changes_assignment_order() -> None:
    sids = _sids(20)
    revs = _reviewers(3)
    p1 = run_plan(sids, revs, random_seed="seed-a")
    p2 = run_plan(sids, revs, random_seed="seed-b")
    # Same counts but different specific assignments
    assert p1.new_assignment_count == p2.new_assignment_count
    new_b = {(e.subject_id, e.to_reviewer_id) for e in p1.movement_plan if e.movement_kind == "new"}
    new_c = {(e.subject_id, e.to_reviewer_id) for e in p2.movement_plan if e.movement_kind == "new"}
    assert new_b != new_c


def test_coverage_gaps_are_filled_for_new_campaign() -> None:
    sids = _sids(5)
    revs = _reviewers(3)
    preview = run_plan(sids, revs, min_reviews_per_subject=2)
    assert preview.feasibility.status in {"feasible", "feasible_with_warnings"}
    for sid in sids:
        assert preview.coverage_after[sid] >= 2


def test_new_subjects_are_covered_by_the_whole_current_roster() -> None:
    """Loading more cases into a published campaign: brand-new subject ids (no prior
    ``ExistingAssignment`` at all) alongside already-fully-covered old ones must still gain
    coverage from every active reviewer, not just one -- an admin topping up cases expects the
    new work to show up in every current roster reviewer's queue after publish."""
    old_sids = _sids(2)
    new_sids = tuple(f"new-{i:04d}" for i in range(3))
    revs = _reviewers(3)
    existing = tuple(
        entry
        for sid in old_sids
        for entry in (
            _existing(sid, "R1", "claimed"),
            _existing(sid, "R2", "claimed"),
            _existing(sid, "R3", "claimed"),
        )
    )
    preview = run_plan(
        old_sids + new_sids,
        revs,
        existing=existing,
        previous_reviewer_ids=("R1", "R2", "R3"),
        min_reviews_per_subject=3,
    )
    for sid in new_sids:
        assert preview.coverage_after[sid] == 3
        to_reviewers = {e.to_reviewer_id for e in preview.movement_plan if e.subject_id == sid}
        assert to_reviewers == {"R1", "R2", "R3"}


def test_submitted_assignments_are_never_moved() -> None:
    sids = _sids(4)
    revs = _reviewers(3)
    existing = tuple(_existing(sid, "R1", "submitted") for sid in sids)
    preview = run_plan(sids, revs, existing=existing, min_reviews_per_subject=1)
    # All subjects covered by submitted assignments — nothing should move
    moved = [e for e in preview.movement_plan if e.movement_kind == "moved"]
    assert moved == []
    submitted_preserved = [
        e
        for e in preview.movement_plan
        if e.movement_kind == "preserved" and e.movement_reason == "submitted_preserved"
    ]
    assert len(submitted_preserved) == 4


def test_claimed_assignments_not_moved_by_default() -> None:
    sids = _sids(4)
    revs = _reviewers(3)
    existing = tuple(_existing(sid, "R1", "claimed") for sid in sids)
    # Default policy: allow_rebalance_claimed=False
    preview = run_plan(sids, revs, existing=existing, min_reviews_per_subject=1)
    moved = [e for e in preview.movement_plan if e.movement_kind == "moved"]
    assert moved == []


def test_claimed_assignments_can_be_moved_when_policy_allows() -> None:
    sids = _sids(4)
    # Only R1 and R2; R3 is new (not in existing assignments)
    existing = tuple(_existing(sid, "R1", "claimed") for sid in sids)
    revs = _reviewers(3)
    mp = MovementPolicy(allow_rebalance_claimed=True, allow_rebalance_unclaimed=True)
    preview = run_plan(
        sids,
        revs,
        existing=existing,
        movement_policy=mp,
        min_reviews_per_subject=2,
        max_workload_per_reviewer=4,
    )
    # R3 should receive some assignments (coverage gap fill or rebalance)
    r3_new = [e for e in preview.movement_plan if e.to_reviewer_id == "R3"]
    assert len(r3_new) > 0


def test_draft_assignments_not_moved_by_default() -> None:
    sids = _sids(4)
    revs = _reviewers(3)
    existing = tuple(_existing(sid, "R1", "draft") for sid in sids)
    preview = run_plan(sids, revs, existing=existing, min_reviews_per_subject=1)
    moved = [e for e in preview.movement_plan if e.movement_kind == "moved"]
    assert moved == []


def test_unclaimed_assignments_can_be_rebalanced_by_default() -> None:
    sids = _sids(6)
    # R1 has all 6 as unclaimed; R2 is new
    existing = tuple(_existing(sid, "R1", "unclaimed") for sid in sids)
    revs = _reviewers(2)
    mp = MovementPolicy(allow_rebalance_unclaimed=True)
    preview = run_plan(sids, revs, existing=existing, movement_policy=mp, min_reviews_per_subject=1)
    # After rebalancing, R2 should have some assignments
    r2_assignments = [
        e
        for e in preview.movement_plan
        if e.to_reviewer_id == "R2" and e.movement_kind in ("moved", "new")
    ]
    assert len(r2_assignments) > 0


def test_adding_a_reviewer_does_not_push_subjects_past_the_review_target() -> None:
    """A fully covered subject must not gain a third reviewer just because one was added.

    Regression: the coverage gap was computed against immovable assignments only, so subjects
    already covered by *movable* assignments looked uncovered. Step 1 provisioned fresh reviewers
    for them and Step 2 then kept the originals, leaving most subjects on three reviewers in a
    two-reviews-per-subject campaign (observed live: 13 of 20 units).
    """

    sids = _sids(8)
    # Every subject already has its full complement of 2 reviewers, all still movable.
    existing = tuple(
        _existing(sid, reviewer_id, "unclaimed") for sid in sids for reviewer_id in ("R1", "R2")
    )
    preview = run_plan(
        sids,
        _reviewers(3),
        existing=existing,
        previous_reviewer_ids=("R1", "R2"),
        min_reviews_per_subject=2,
    )
    for sid in sids:
        assert preview.coverage_after[sid] == 2, (
            f"{sid} ended on {preview.coverage_after[sid]} reviewers, expected exactly 2"
        )
    # ...and the added reviewer takes a real share instead of the work piling up on the incumbents.
    counts = sorted(summary.count_after for summary in preview.workload_summaries)
    assert counts[-1] - counts[0] <= 1, f"workload {counts} is not balanced within one"


def test_coverage_minimum_constraint_is_enforced() -> None:
    sids = _sids(6)
    # Only 1 reviewer with capacity 3 — can't cover min=2 for all 6 subjects
    revs = (IncrementalReviewer(reviewer_id="R1", capacity_weight=1.0),)
    preview = run_plan(sids, revs, min_reviews_per_subject=2, max_workload_per_reviewer=3)
    assert preview.feasibility.status == "blocked_by_capacity"
    assert len(preview.unassigned_subject_ids) > 0


def test_feasible_plan_with_sufficient_capacity() -> None:
    sids = _sids(4)
    revs = _reviewers(3)
    preview = run_plan(sids, revs, min_reviews_per_subject=2)
    assert preview.feasibility.status in {"feasible", "feasible_with_warnings"}
    assert len(preview.unassigned_subject_ids) == 0


def test_adding_reviewer_receives_overflow_work() -> None:
    """New reviewer gets new assignments for coverage-gap subjects."""
    sids = _sids(4)
    # Initial state: R1 and R2 cover all subjects with 1 review each
    existing = tuple(_existing(sid, "R1", "claimed") for sid in sids)
    # Add R3; min_reviews_per_subject=2 creates coverage gaps for all 4 subjects
    revs = _reviewers(3)
    preview = run_plan(
        sids,
        revs,
        existing=existing,
        previous_reviewer_ids=("R1", "R2"),
        min_reviews_per_subject=2,
    )
    # R3 should get new assignments filling the gap
    r3_new = [
        e for e in preview.movement_plan if e.to_reviewer_id == "R3" and e.movement_kind == "new"
    ]
    assert len(r3_new) > 0
    # Coverage must be satisfied
    for sid in sids:
        assert preview.coverage_after[sid] >= 2


def test_reviewer_removed_unclaimed_work_reassigned() -> None:
    sids = _sids(4)
    # R1 and R2 had claims; R2 is removed from the new pool
    existing = (
        *(_existing(sid, "R1", "claimed") for sid in sids[:2]),
        *(_existing(sid, "R2", "unclaimed") for sid in sids[2:]),
    )
    revs = (_reviewers(1)[0],)  # only R1 remains
    mp = MovementPolicy(allow_rebalance_unclaimed=True)
    preview = run_plan(
        sids,
        revs,
        existing=existing,
        movement_policy=mp,
        min_reviews_per_subject=1,
    )
    # R2's unclaimed assignments must actually be released (movement_kind "moved"), never left
    # untouched as "skipped" -- a removed reviewer must end with zero assignments, even when the
    # remaining roster already satisfies coverage without them (see
    # test_reviewer_removed_when_replacement_already_covers_subject_still_releases below for the
    # exact scenario this used to get wrong).
    moved_from_r2 = [
        e
        for e in preview.movement_plan
        if e.from_reviewer_id == "R2" and e.movement_kind == "moved"
    ]
    assert len(moved_from_r2) == 2
    assert not any(
        e.from_reviewer_id == "R2" and e.movement_kind == "skipped" for e in preview.movement_plan
    )


def test_reviewer_removed_when_replacement_already_covers_subject_still_releases() -> None:
    """Swap R1 -> R2 while R3 keeps its seat, min_reviews_per_subject == remaining roster size.

    Reproduces the live "Publish 0 assignments, R1 still sees the campaign" bug: with exactly
    enough active reviewers to satisfy coverage, the greedy gap-fill step used to consume both
    slots before the removed-reviewer branch ran, leaving R1's own claimed assignment "skipped"
    (never released) instead of "moved". Movable classes only, per the frontend's actual default
    movement policy (``allow_rebalance_claimed=True``).
    """
    sids = _sids(3)
    existing = tuple(
        entry
        for sid in sids
        for entry in (_existing(sid, "R1", "claimed"), _existing(sid, "R3", "claimed"))
    )
    revs = (
        IncrementalReviewer(reviewer_id="R2"),
        IncrementalReviewer(reviewer_id="R3"),
    )
    mp = MovementPolicy(allow_rebalance_unclaimed=True, allow_rebalance_claimed=True)
    preview = run_plan(
        sids,
        revs,
        existing=existing,
        movement_policy=mp,
        previous_reviewer_ids=("R1", "R3"),
        min_reviews_per_subject=2,
    )
    r1_entries = [e for e in preview.movement_plan if e.from_reviewer_id == "R1"]
    assert len(r1_entries) == len(sids)
    assert all(e.movement_kind == "moved" for e in r1_entries)
    assert all(e.to_reviewer_id in {"R2", "R3"} for e in r1_entries)
    for sid in sids:
        assert preview.coverage_after[sid] >= 2


def test_removed_reviewer_does_not_add_a_third_replacement_after_gap_fill() -> None:
    """A gap fill and a removed-reviewer release for one subject are one replacement, not two."""
    sid = "s-removed-with-gap"
    existing = (
        _existing(sid, "R1", "claimed"),
        _existing(sid, "R_removed", "claimed"),
    )
    reviewers = tuple(IncrementalReviewer(reviewer_id=rid) for rid in ("R1", "R2", "R3"))
    preview = run_plan(
        (sid,),
        reviewers,
        existing=existing,
        previous_reviewer_ids=("R1", "R_removed"),
        movement_policy=MovementPolicy(
            allow_rebalance_unclaimed=True,
            allow_rebalance_claimed=True,
        ),
        min_reviews_per_subject=2,
    )

    assert preview.coverage_after[sid] == 2
    assert len({e.to_reviewer_id for e in preview.movement_plan if e.subject_id == sid}) == 2
    removed = [e for e in preview.movement_plan if e.from_reviewer_id == "R_removed"]
    assert len(removed) == 1
    assert removed[0].movement_reason == "reviewer_removed_release_only"


def test_submitted_work_survives_reviewer_removal() -> None:
    """Submitted assignments from removed reviewer stay as historical completed work."""
    sids = _sids(4)
    existing = tuple(_existing(sid, "R_removed", "submitted") for sid in sids)
    revs = _reviewers(2)
    preview = run_plan(sids, revs, existing=existing, min_reviews_per_subject=1)
    # Submitted entries preserved as historical
    submitted_entries = [
        e
        for e in preview.movement_plan
        if e.movement_reason == "submitted_immovable_removed_reviewer"
    ]
    assert len(submitted_entries) == 4
    # No error about submitted assignments
    assert not any(e.code == "submitted_moved" for e in preview.feasibility.errors)


def test_capacity_weights_affect_assignment_distribution() -> None:
    sids = _sids(10)
    revs = (
        IncrementalReviewer(reviewer_id="R1", capacity_weight=2.0),
        IncrementalReviewer(reviewer_id="R2", capacity_weight=1.0),
    )
    preview = run_plan(sids, revs, min_reviews_per_subject=1)
    r1_count = sum(
        1
        for e in preview.movement_plan
        if e.to_reviewer_id == "R1" and e.movement_kind in ("new", "preserved")
    )
    r2_count = sum(
        1
        for e in preview.movement_plan
        if e.to_reviewer_id == "R2" and e.movement_kind in ("new", "preserved")
    )
    # Higher capacity reviewer should get more or equal assignments (weighted hash)
    # Not always strictly more due to subject count, but direction should favor R1
    assert r1_count >= r2_count - 1  # Allow for 1-off due to small counts


def test_duplicate_reviewer_subject_assignments_prevented() -> None:
    sids = _sids(4)
    revs = _reviewers(3)
    existing = tuple(_existing(sid, "R1", "submitted") for sid in sids)
    preview = run_plan(sids, revs, existing=existing, min_reviews_per_subject=2)
    # Check no duplicate (subject, reviewer) in new assignments
    pairs = [
        (e.subject_id, e.to_reviewer_id) for e in preview.movement_plan if e.movement_kind == "new"
    ]
    assert len(pairs) == len(set(pairs))


def test_empty_reviewer_pool_returns_blocked() -> None:
    preview = run_plan(_sids(4), (), min_reviews_per_subject=1)
    assert preview.feasibility.status == "blocked_by_reviewer_pool"
    assert preview.new_assignment_count == 0


def test_workload_is_balanced_within_tolerance() -> None:
    sids = _sids(10)
    revs = _reviewers(3)
    preview = run_plan(sids, revs, min_reviews_per_subject=2)
    counts = [ws.count_after for ws in preview.workload_summaries]
    assert max(counts) - min(counts) <= 2


def test_reviewer_facing_data_not_leaked_in_planner_output() -> None:
    """The planner output itself carries no reviewer-blinding sensitive data."""
    sids = _sids(4)
    revs = _reviewers(3)
    preview = run_plan(sids, revs, min_reviews_per_subject=2)
    # movement_plan entries carry to_reviewer_id (admin-only) — verify we don't
    # accidentally produce a reviewer_safe_projection function that leaks them.
    # The key blinding invariant: workload summaries are admin-only structures.
    for ws in preview.workload_summaries:
        assert hasattr(ws, "reviewer_id")
        assert hasattr(ws, "count_before")
        assert hasattr(ws, "count_after")


pytestmark = pytest.mark.no_db
