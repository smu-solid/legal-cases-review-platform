"""Shared planning state and ordered preservation, coverage, and rebalancing passes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from review_platform.review.incremental_planner_types import (
    IncrementalPolicy,
    IncrementalReviewer,
    MovementClass,
    MovementEntry,
)

if TYPE_CHECKING:
    from review_platform.review.incremental_planner import IncrementalPlanner


@dataclass
class IncrementalPlanState:
    """Mutable state for one plan; never shared across requests or persisted."""

    planner: IncrementalPlanner
    subject_ids: tuple[str, ...]
    active: tuple[IncrementalReviewer, ...]
    by_subject: dict[str, dict[str, MovementClass]]
    policy: IncrementalPolicy
    active_ids: frozenset[str] = field(init=False)
    assigned_to: dict[str, set[str]] = field(init=False)
    workload_current: dict[str, int] = field(init=False)
    movement_plan: list[MovementEntry] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.active_ids = frozenset(r.reviewer_id for r in self.active)
        self.assigned_to = {sid: set() for sid in self.subject_ids}
        self.workload_current = {rid: 0 for rid in self.active_ids}

    def preserve_immutable(self) -> None:
        mp = self.policy.movement_policy
        for sid in self.subject_ids:
            for rid, mc in self.by_subject[sid].items():
                movable = self.planner._is_movable(mc, mp)
                if not movable:
                    if rid in self.active_ids:
                        self.assigned_to[sid].add(rid)
                        self.workload_current[rid] += 1
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=None,
                                to_reviewer_id=rid,
                                movement_kind="preserved",
                                movement_reason=f"{mc}_preserved",
                            )
                        )
                    # Reviewer removed from pool + immovable: record as preserved (submitted stays)
                    elif mc == "submitted":
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=rid,
                                movement_kind="preserved",
                                movement_reason="submitted_immovable_removed_reviewer",
                            )
                        )

    def fill_coverage_gaps(self, coverage_before: dict[str, int]) -> int:
        workload_limits = {r.reviewer_id: r.workload_limit for r in self.active}
        mp = self.policy.movement_policy
        new_count = 0
        sorted_sids = sorted(
            self.subject_ids,
            key=lambda sid: (
                coverage_before.get(sid, 0),
                self.planner._stable_hash(sid, self.policy.random_seed),
                sid,
            ),
        )
        for sid in sorted_sids:
            # Coverage a subject already has, counting BOTH the immovable assignments seeded into
            # ``assigned_to`` above AND the movable ones from still-active reviewers that Step 2
            # will retain (it either preserves them or *moves* them, which is coverage-neutral).
            # Counting only the immovable ones treats an already-covered subject as uncovered and
            # provisions fresh reviewers on top of assignments that are then kept -- that is how a
            # 2-reviews-per-case campaign ended up with three reviewers on most of its units after
            # a reviewer was added to the roster. Movable assignments held by reviewers no longer
            # in the pool are excluded: Step 2 reassigns those, so they are not retained coverage.
            retained_ids = {
                rid
                for rid, mc in self.by_subject[sid].items()
                if self.planner._is_movable(mc, mp)
                and rid in self.active_ids
                and rid not in self.assigned_to[sid]
            }
            gap = self.policy.min_reviews_per_subject - (
                len(self.assigned_to[sid]) + len(retained_ids)
            )
            while gap > 0:
                # ``retained_ids`` are excluded as candidates as well as counted: they are not in
                # ``assigned_to[sid]`` yet, so without this the gap could be "filled" by the very
                # reviewer already covering the subject. Step 2 then folds that pick into an
                # ``already_covered`` no-op and the subject silently finishes under its minimum.
                chosen = self.planner._select_balanced(
                    sid,
                    self.active,
                    self.assigned_to[sid] | retained_ids,
                    self.workload_current,
                    workload_limits,
                    self.policy,
                )
                if chosen is None:
                    break
                self.assigned_to[sid].add(chosen)
                self.workload_current[chosen] += 1
                self.movement_plan.append(
                    MovementEntry(
                        subject_id=sid,
                        from_reviewer_id=None,
                        to_reviewer_id=chosen,
                        movement_kind="new",
                        movement_reason="coverage_gap",
                    )
                )
                gap -= 1
                new_count += 1

        return new_count

    def rebalance_movable(self) -> int:
        mp = self.policy.movement_policy
        moved_count = 0
        # Rebalancing is planned up front rather than decided subject-by-subject. The old rule
        # ("move if this reviewer is above the running mean") only ever shed a reviewer's overflow:
        # each move dropped them back under the mean, so the next subject preserved instead of
        # moving, and a newly added reviewer ended up with the scraps (77/77/50 where 68/68/68 was
        # available). Instead, work out what each reviewer would hold if nothing moved, compare
        # that with an even share, and let Step 2 shed exactly the surplus onto exactly the
        # reviewers who are short.
        # An even split of ``total`` over ``n`` reviewers is some of them on ``floor`` and the rest
        # on ``ceil``; a donor may therefore shed all the way down to ``floor``, while a receiver
        # may take up to ``ceil``. Budgeting the donor against ``ceil`` instead would strand the
        # short reviewer one whole slot below everyone else on totals that do not divide evenly.
        total_coverage = len(self.subject_ids) * self.policy.min_reviews_per_subject
        reviewer_count = len(self.active_ids)
        target_floor = total_coverage // reviewer_count if reviewer_count else 0
        target_ceil = -(-total_coverage // reviewer_count) if reviewer_count else 0
        # What each reviewer ends up holding if Step 2 moves nothing. That is everything already
        # committed above -- immovable assignments plus the coverage-gap picks Step 1 just made,
        # both of which are in ``workload_current`` -- plus the movable assignments Step 2 is about
        # to walk. Counting only the second group would ignore Step 1 entirely and hand a reviewer
        # who was just given a pile of gap work a shedding budget of zero.
        projected: dict[str, int] = {
            rid: self.workload_current.get(rid, 0) for rid in self.active_ids
        }
        for sid in self.subject_ids:
            for rid, mc in self.by_subject[sid].items():
                if (
                    rid in self.active_ids
                    and self.planner._is_movable(mc, mp)
                    and rid not in self.assigned_to[sid]
                ):
                    projected[rid] += 1
        to_shed = {rid: max(0, count - target_floor) for rid, count in projected.items()}
        capacity = {rid: max(0, target_ceil - count) for rid, count in projected.items()}
        for sid in self.subject_ids:
            for rid, mc in sorted(self.by_subject[sid].items()):
                if not self.planner._is_movable(mc, mp):
                    continue
                if rid in self.assigned_to[sid]:
                    # Already covered by a preserved/new entry above
                    self.movement_plan.append(
                        MovementEntry(
                            subject_id=sid,
                            from_reviewer_id=rid,
                            to_reviewer_id=rid,
                            movement_kind="preserved",
                            movement_reason="already_covered",
                        )
                    )
                    continue
                if rid not in self.active_ids:
                    # Step 1 may already have filled the slot vacated by this removed reviewer.
                    # Include active movable assignments that this pass has not reached yet: Step
                    # 1 counted them as retained coverage, so assigning another replacement here
                    # would push the subject above its configured review target.
                    pending_retained_ids = {
                        other_rid
                        for other_rid, other_mc in self.by_subject[sid].items()
                        if other_rid in self.active_ids
                        and other_rid not in self.assigned_to[sid]
                        and self.planner._is_movable(other_mc, mp)
                    }
                    if (
                        len(self.assigned_to[sid]) + len(pending_retained_ids)
                        >= self.policy.min_reviews_per_subject
                    ):
                        release_target = min(self.assigned_to[sid])
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=release_target,
                                movement_kind="moved",
                                movement_reason="reviewer_removed_release_only",
                            )
                        )
                        moved_count += 1
                        continue
                    # Coverage still has a real gap: assign one replacement.
                    best = self.planner._find_best_reviewer(
                        sid, self.active, self.assigned_to[sid], self.workload_current, self.policy
                    )
                    if best is not None:
                        self.assigned_to[sid].add(best)
                        self.workload_current[best] += 1
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=best,
                                movement_kind="moved",
                                movement_reason="reviewer_removed",
                            )
                        )
                        moved_count += 1
                    elif self.assigned_to[sid]:
                        # No active reviewer has spare room, but this subject is already fully
                        # covered by the active roster -- there is no coverage gap left to fill.
                        # The removed reviewer's stale claim must still be released rather than
                        # silently left with them, so attribute the release to a reviewer who
                        # already covers the subject (a same-owner no-op assignment-wise). This
                        # reuses the existing "moved" movement kind -- adding a distinct kind
                        # would need a check-constraint migration, which this fix avoids.
                        release_target = min(self.assigned_to[sid])
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=release_target,
                                movement_kind="moved",
                                movement_reason="reviewer_removed_release_only",
                            )
                        )
                        moved_count += 1
                    else:
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=rid,
                                movement_kind="skipped",
                                movement_reason="no_eligible_replacement",
                            )
                        )
                    continue
                # Reviewer still active: shed this assignment only while this reviewer is still
                # carrying surplus against the even share, and only onto a reviewer who is still
                # short of it. Both budgets are fixed before the pass, so every move is one the
                # finished plan needs and no move has to be undone later.
                if to_shed.get(rid, 0) > 0:
                    # Two exclusions on top of "already covers this subject", both of which would
                    # otherwise make the search return a reviewer that cannot take the work and
                    # silently waste a move the plan had budgeted for:
                    #   * ``rid`` itself -- it is not in ``assigned_to[sid]`` yet (that only happens
                    #     when the assignment is kept), so it is a candidate for its own slot;
                    #   * anyone already at their share -- the search ranks by workload and returns
                    #     a single best, so one full reviewer at the front of the ranking would
                    #     block a move that a different, still-short reviewer could have taken.
                    unavailable = {r for r, left in capacity.items() if left <= 0}
                    best = self.planner._find_best_reviewer(
                        sid,
                        self.active,
                        self.assigned_to[sid] | {rid} | unavailable,
                        self.workload_current,
                        self.policy,
                    )
                    if best is not None and capacity.get(best, 0) > 0:
                        to_shed[rid] -= 1
                        capacity[best] -= 1
                        self.assigned_to[sid].add(best)
                        # Only the receiver's workload changes: ``rid`` is never credited with this
                        # subject (the ``continue`` below skips the keep branch), so decrementing
                        # it here would subtract a slot it was never given and skew every later
                        # balance decision that reads this counter.
                        self.workload_current[best] += 1
                        self.movement_plan.append(
                            MovementEntry(
                                subject_id=sid,
                                from_reviewer_id=rid,
                                to_reviewer_id=best,
                                movement_kind="moved",
                                movement_reason="workload_rebalance",
                            )
                        )
                        moved_count += 1
                        continue
                self.assigned_to[sid].add(rid)
                self.workload_current[rid] += 1
                self.movement_plan.append(
                    MovementEntry(
                        subject_id=sid,
                        from_reviewer_id=None,
                        to_reviewer_id=rid,
                        movement_kind="preserved",
                        movement_reason="workload_balanced",
                    )
                )

        return moved_count
