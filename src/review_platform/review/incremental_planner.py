"""Pure incremental allocation planner using weighted rendezvous hashing.

Storage-agnostic: accepts existing assignment classifications, subjects, and reviewers,
then returns an incremental preview. Service layer handles DB loading and persistence.

Algorithm:
  1. Classify existing assignments by movement class.
  2. Preserve immovable assignments (submitted, claimed, draft per policy).
  3. Fill coverage gaps using rendezvous-ranked reviewers.
  4. Optionally rebalance movable assignments for workload balance.
  5. Return structured feasibility + movement plan.
"""

from __future__ import annotations

import hashlib
import math

from review_platform.review.incremental_phases import IncrementalPlanState
from review_platform.review.incremental_planner_types import (
    INCREMENTAL_PLANNER_VERSION,
    ExistingAssignment,
    IncrementalAllocationPreview,
    IncrementalFeasibilityIssue,
    IncrementalFeasibilityResult,
    IncrementalFeasibilityStatus,
    IncrementalPolicy,
    IncrementalReviewer,
    MovementClass,
    MovementEntry,
    MovementPolicy,
    WorkloadSummary,
)

__all__ = [
    "INCREMENTAL_PLANNER_VERSION",
    "ExistingAssignment",
    "IncrementalAllocationPreview",
    "IncrementalFeasibilityIssue",
    "IncrementalFeasibilityResult",
    "IncrementalFeasibilityStatus",
    "IncrementalPlanner",
    "IncrementalPolicy",
    "IncrementalReviewer",
    "MovementClass",
    "MovementEntry",
    "MovementPolicy",
    "WorkloadSummary",
]


class IncrementalPlanner:
    """Deterministic incremental reviewer allocation planner.

    Accepts a frozen snapshot of existing assignments plus the new reviewer pool, and
    returns a preview describing the minimal set of changes needed to satisfy minimum
    coverage and workload-balance constraints.
    """

    def plan(
        self,
        *,
        subject_ids: tuple[str, ...],
        reviewers: tuple[IncrementalReviewer, ...],
        existing_assignments: tuple[ExistingAssignment, ...],
        policy: IncrementalPolicy,
        previous_reviewer_ids: tuple[str, ...],
    ) -> IncrementalAllocationPreview:
        active = tuple(r for r in reviewers if r.active and r.authorized)

        input_errors = self._validate_inputs(active, policy)
        if input_errors:
            status: IncrementalFeasibilityStatus = "blocked_by_reviewer_pool"
            return IncrementalAllocationPreview(
                feasibility=IncrementalFeasibilityResult(status=status, errors=tuple(input_errors)),
                movement_plan=(),
                reviewer_pool_before=previous_reviewer_ids,
                reviewer_pool_after=tuple(r.reviewer_id for r in active),
                workload_summaries=(),
                coverage_before={},
                coverage_after={},
                new_assignment_count=0,
                moved_assignment_count=0,
                preserved_assignment_count=0,
                unassigned_subject_ids=subject_ids,
            )

        mp = policy.movement_policy
        active_ids = frozenset(r.reviewer_id for r in active)

        # Map existing assignments by subject
        by_subject: dict[str, dict[str, MovementClass]] = {sid: {} for sid in subject_ids}
        for ea in existing_assignments:
            if ea.subject_id in by_subject:
                by_subject[ea.subject_id][ea.reviewer_id] = ea.movement_class

        # Workload before (count active-reviewer assignments, all classes)
        workload_before: dict[str, int] = {rid: 0 for rid in active_ids}
        for ea in existing_assignments:
            if ea.reviewer_id in workload_before:
                workload_before[ea.reviewer_id] += 1

        state = IncrementalPlanState(
            planner=self,
            subject_ids=subject_ids,
            active=active,
            by_subject=by_subject,
            policy=policy,
        )
        assigned_to = state.assigned_to
        workload_current = state.workload_current
        movement_plan = state.movement_plan
        state.preserve_immutable()

        # Coverage before: count non-movable assignments per subject (regardless of reviewer pool)
        coverage_before: dict[str, int] = {}
        for sid in subject_ids:
            coverage_before[sid] = sum(
                1 for rid, mc in by_subject[sid].items() if not self._is_movable(mc, mp)
            )

        # Step 1: fill coverage gaps with capacity-aware greedy balancing. Each pick takes the
        # reviewer with the lowest capacity-normalized workload (workload / capacity_weight), so
        # equal-weight pools stay balanced and a weight-2 reviewer absorbs roughly twice the share.
        # Ties break on the weighted rendezvous score, keeping the result deterministic per seed.
        new_count = state.fill_coverage_gaps(coverage_before)
        moved_count = state.rebalance_movable()

        coverage_after = {sid: len(assigned_to[sid]) for sid in subject_ids}
        workload_summaries = tuple(
            WorkloadSummary(
                reviewer_id=rid,
                count_before=workload_before.get(rid, 0),
                count_after=workload_current.get(rid, 0),
            )
            for rid in sorted(active_ids)
        )
        unassigned = tuple(
            sid for sid in subject_ids if coverage_after[sid] < policy.min_reviews_per_subject
        )
        preserved_count = sum(1 for e in movement_plan if e.movement_kind == "preserved")
        feasibility = self._compute_feasibility(unassigned, workload_current, policy)
        return IncrementalAllocationPreview(
            feasibility=feasibility,
            movement_plan=tuple(movement_plan),
            reviewer_pool_before=previous_reviewer_ids,
            reviewer_pool_after=tuple(sorted(active_ids)),
            workload_summaries=workload_summaries,
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            new_assignment_count=new_count,
            moved_assignment_count=moved_count,
            preserved_assignment_count=preserved_count,
            unassigned_subject_ids=unassigned,
        )

    @staticmethod
    def _is_movable(mc: MovementClass, mp: MovementPolicy) -> bool:
        if mc == "submitted":
            return False
        if mc == "claimed":
            return mp.allow_rebalance_claimed
        if mc == "draft":
            return mp.allow_rebalance_draft
        return mp.allow_rebalance_unclaimed  # unclaimed

    @staticmethod
    def _validate_inputs(
        active: tuple[IncrementalReviewer, ...],
        policy: IncrementalPolicy,
    ) -> list[IncrementalFeasibilityIssue]:
        errors: list[IncrementalFeasibilityIssue] = []
        if len(active) == 0:
            errors.append(
                IncrementalFeasibilityIssue(
                    "no_active_reviewers",
                    "At least one active authorized reviewer is required.",
                )
            )
        if len({r.reviewer_id for r in active}) != len(active):
            errors.append(
                IncrementalFeasibilityIssue(
                    "duplicate_reviewers", "Reviewer IDs must be unique within the pool."
                )
            )
        if policy.min_reviews_per_subject < 1:
            errors.append(
                IncrementalFeasibilityIssue(
                    "invalid_min_reviews",
                    "min_reviews_per_subject must be at least 1.",
                )
            )
        return errors

    @staticmethod
    def _rendezvous_score(
        subject_id: str,
        reviewer: IncrementalReviewer,
        policy: IncrementalPolicy,
    ) -> float:
        """Weighted rendezvous (HRW) score for one reviewer/subject pair; higher wins."""
        raw = hashlib.sha256(
            f"{subject_id}:{reviewer.reviewer_id}:{policy.random_seed}:"
            f"{policy.allocation_policy_version}".encode()
        ).digest()
        uniform = int.from_bytes(raw[:8], "big") / 2**64
        return reviewer.capacity_weight / (-math.log(uniform + 1e-10))

    @staticmethod
    def _select_balanced(
        subject_id: str,
        reviewers: tuple[IncrementalReviewer, ...],
        already_assigned: set[str],
        workload: dict[str, int],
        workload_limits: dict[str, int | None],
        policy: IncrementalPolicy,
    ) -> str | None:
        """Pick the eligible reviewer with the lowest capacity-normalized load for this subject.

        Eligibility excludes reviewers already on the subject and anyone at their per-reviewer or
        policy workload cap. Selection minimizes ``workload / capacity_weight``; ties break on the
        (higher) weighted rendezvous score and finally reviewer id, so output is deterministic.
        """
        best: str | None = None
        best_key: tuple[float, float, str] | None = None
        for reviewer in reviewers:
            rid = reviewer.reviewer_id
            if rid in already_assigned:
                continue
            wl = workload.get(rid, 0)
            limit = workload_limits.get(rid)
            if limit is not None and wl >= limit:
                continue
            if (
                policy.max_workload_per_reviewer is not None
                and wl >= policy.max_workload_per_reviewer
            ):
                continue
            weight = reviewer.capacity_weight or 1.0
            score = IncrementalPlanner._rendezvous_score(subject_id, reviewer, policy)
            key = (wl / weight, -score, rid)
            if best_key is None or key < best_key:
                best_key = key
                best = rid
        return best

    @staticmethod
    def _find_best_reviewer(
        subject_id: str,
        reviewers: tuple[IncrementalReviewer, ...],
        already_assigned: set[str],
        workload: dict[str, int],
        policy: IncrementalPolicy,
    ) -> str | None:
        candidates = [
            r
            for r in reviewers
            if r.reviewer_id not in already_assigned
            and (r.workload_limit is None or workload.get(r.reviewer_id, 0) < r.workload_limit)
            and (
                policy.max_workload_per_reviewer is None
                or workload.get(r.reviewer_id, 0) < policy.max_workload_per_reviewer
            )
        ]
        if not candidates:
            return None
        raw = hashlib.sha256(
            f"{subject_id}:{policy.random_seed}:{policy.allocation_policy_version}".encode()
        ).digest()
        uniform_base = int.from_bytes(raw[:8], "big") / 2**64
        return min(
            candidates,
            key=lambda r: (
                workload.get(r.reviewer_id, 0),
                -r.capacity_weight / (-math.log(uniform_base + 1e-10)),
                r.reviewer_id,
            ),
        ).reviewer_id

    @staticmethod
    def _stable_hash(value: str, seed: str) -> float:
        digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    @staticmethod
    def _compute_feasibility(
        unassigned: tuple[str, ...],
        workload: dict[str, int],
        policy: IncrementalPolicy,
    ) -> IncrementalFeasibilityResult:
        errors: list[IncrementalFeasibilityIssue] = []
        warnings: list[IncrementalFeasibilityIssue] = []
        if unassigned:
            errors.append(
                IncrementalFeasibilityIssue(
                    "coverage_gap_unresolved",
                    f"{len(unassigned)} subject(s) could not reach the minimum coverage of "
                    f"{policy.min_reviews_per_subject} review(s). Increase reviewer capacity, "
                    "relax max_workload_per_reviewer, or add more reviewers.",
                )
            )
        if policy.max_workload_per_reviewer is not None:
            over = [rid for rid, wl in workload.items() if wl > policy.max_workload_per_reviewer]
            if over:
                warnings.append(
                    IncrementalFeasibilityIssue(
                        "workload_exceeds_max",
                        f"{len(over)} reviewer(s) exceed max_workload_per_reviewer.",
                    )
                )
        if workload:
            counts = list(workload.values())
            imbalance = max(counts) - min(counts)
            if imbalance > 1:
                warnings.append(
                    IncrementalFeasibilityIssue(
                        "workload_imbalance",
                        f"Reviewer workload imbalance is {imbalance} after allocation.",
                    )
                )
        status: IncrementalFeasibilityStatus
        if errors:
            status = "blocked_by_capacity"
        elif warnings:
            status = "feasible_with_warnings"
        else:
            status = "feasible"
        return IncrementalFeasibilityResult(
            status=status,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
