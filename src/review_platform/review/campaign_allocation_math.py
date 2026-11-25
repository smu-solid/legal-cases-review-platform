"""Simple campaign allocation math: ``cases * minimum_reviews_per_case``, and a balanced,
seeded case/reviewer preview plan.

Deliberately distinct from ``review.allocation.*`` (the pairwise/global-overlap allocation
engine behind the existing preview/persist/publish endpoints). This module only computes a
read-only preview an admin can review before driving that existing engine; it never persists an
``Assignment`` row itself.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

InfeasibilityReason = tuple[str, str] | None

# The ``review_units`` CHECK constraint (``ck_review_unit_required_reviews``) enforces the same
# floor at the database layer; keep both in sync if this ever changes.
MINIMUM_REVIEWS_PER_CASE_DEFAULT = 2

_SEED_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._:-]")


def campaign_allocation_seed(campaign_key: str) -> str:
    """The one seed both allocation engines must agree on for a given campaign.

    Unification decision: seed derives *only* from the campaign's immutable ``key`` (never
    the campaign id, the selected-reviewer roster, or anything else that can change), so
    a re-preview stays stable across roster edits and matches whatever the persist path
    already used -- ``apps/web/src/routes/admin/CampaignDetailPage.tsx`` already builds
    ``AllocationPolicyInput.random_seed`` as ``f"campaign-{sanitize(campaign_key)}"`` for
    the persist/publish flow; this mirrors that exact formula so
    ``campaign_allocation_summary``'s preview and the real persisted plan are seeded
    identically. Previously the preview used ``str(campaign_id)`` -- a different seed
    from the one the frontend sent at persist time -- which was the root cause of
    preview/persist plans diverging even before the algorithms themselves were unified."""

    return f"campaign-{_SEED_SANITIZE_PATTERN.sub('-', campaign_key)}"


def resolve_minimum_reviews_per_case(value: int | None) -> int:
    """Resolve an optional, request-supplied ``minimum_reviews_per_case`` to its effective
    value."""

    return value if value is not None else MINIMUM_REVIEWS_PER_CASE_DEFAULT


@dataclass(frozen=True)
class CampaignCase:
    review_subject_id: uuid.UUID
    display_title: str
    # The case's stable source identity (``snapshot_local_case_external_id``). This -- not the
    # opaque
    # representative ``review_subject_id`` -- is the seeding key, because the persist-path planner
    # keys its allocation subjects by exactly this id (see ``AllocationServiceBase._case_key``).
    # Both engines must seed by the same per-case string or their plans diverge despite the shared
    # core and shared seed (see ``campaign_allocation_seed``).
    case_external_id: str


@dataclass(frozen=True)
class AllocationPlanEntry:
    case: CampaignCase
    reviewer_ids: list[uuid.UUID]


def compute_total_assignments(selected_cases: int, minimum_reviews_per_case: int) -> int:
    return selected_cases * minimum_reviews_per_case


def compute_estimated_assignments_per_reviewer(
    total_assignments: int, selected_reviewers: int
) -> int:
    if selected_reviewers <= 0:
        return 0
    return math.ceil(total_assignments / selected_reviewers)


def infeasibility_reason(
    *, selected_cases: int, selected_reviewers: int, minimum_reviews_per_case: int
) -> InfeasibilityReason:
    """Return ``(code, message)`` when the campaign cannot be allocated yet, else ``None``.

    A case needs ``minimum_reviews_per_case`` *distinct* reviewers (one reviewer never reviews the
    same case twice), so feasibility requires at least that many selected reviewers.
    """

    if selected_cases == 0:
        return ("no_review_units", "The campaign has no review units to allocate yet.")
    if selected_reviewers == 0:
        # ``minimum_reviews_per_case`` has a hard floor of 2 (see MINIMUM_REVIEWS_PER_CASE_DEFAULT
        # and its below-2 rejection elsewhere), so "at least one" here would understate the real
        # requirement -- state the actual number, matching the wording used once reviewers exist.
        return (
            "no_selected_reviewers",
            f"No active reviewers are selected yet. Add at least {minimum_reviews_per_case} "
            "before allocating.",
        )
    if selected_reviewers == 1 and minimum_reviews_per_case >= 2:
        return (
            "insufficient_reviewers",
            "At least 2 reviewers are required when the number of reviews per case is 2 or more.",
        )
    if selected_reviewers < minimum_reviews_per_case:
        return (
            "insufficient_reviewers",
            f"At least {minimum_reviews_per_case} reviewers are required so every case can reach "
            f"{minimum_reviews_per_case} distinct reviews.",
        )
    return None


def build_allocation_plan(
    cases: Sequence[CampaignCase],
    reviewer_ids: Sequence[uuid.UUID],
    minimum_reviews_per_case: int,
    *,
    seed: str,
) -> list[AllocationPlanEntry]:
    """Balanced, seeded preview plan: every case gets ``minimum_reviews_per_case`` distinct
    reviewers via :func:`build_uniform_coverage_assignment`, the shared pure core also used by
    ``review.allocation.planner.AllocationPlanner`` (see its module docstring for why the two
    engines share this one algorithm).

    Callers must only invoke this once ``infeasibility_reason`` returns ``None`` -- it assumes
    ``len(reviewer_ids) >= minimum_reviews_per_case``.
    """

    case_count = len(cases)
    reviewer_count = len(reviewer_ids)
    if case_count == 0 or reviewer_count == 0:
        return []

    case_keys = [case.case_external_id for case in cases]
    reviewer_keys = [str(reviewer_id) for reviewer_id in reviewer_ids]
    reviewer_by_key = dict(zip(reviewer_keys, reviewer_ids, strict=True))
    assignments = build_uniform_coverage_assignment(
        case_keys, reviewer_keys, minimum_reviews_per_case, seed=seed
    )

    return [
        AllocationPlanEntry(
            case=cases[i], reviewer_ids=[reviewer_by_key[key] for key in assignments[i]]
        )
        for i in range(case_count)
    ]


def build_uniform_coverage_assignment(
    case_keys: Sequence[str],
    reviewer_keys: Sequence[str],
    reviews_per_case: int,
    *,
    seed: str,
    initial_workload: dict[str, int] | None = None,
) -> list[list[str]]:
    """Shared pure core: for each of ``case_keys`` (by input position), return exactly
    ``reviews_per_case`` distinct reviewer keys, chosen so that:

    * total assignments == ``len(case_keys) * reviews_per_case``;
    * every case gets exactly ``reviews_per_case`` distinct reviewers (never repeated on one case);
    * reviewer workloads land on ``floor(T/N)``/``ceil(T/N)`` only (``max - min <= 1``);
    * pairwise reviewer overlap is balanced as far as mathematically possible -- not a contiguous
      block, not a sliding A/B, B/C window, and not dependent on lexicographic reviewer ordering;
    * deterministic and reproducible from ``seed`` alone (same inputs -> identical output, no
      ``random.Random``/``hash()`` -- see ``_stable_random``).

    Algorithm: cases are processed in a seeded order (stable hash of ``seed`` + case key, *not*
    input position, so re-ordering the input list never changes the plan). For each case, the
    ``reviews_per_case`` reviewers are chosen one at a time, each pick minimizing the tuple
    ``(workload[reviewer], overlap_with_already_chosen_for_this_case, stable_hash(seed, case_key,
    reviewer_key))`` -- workload balance first, then overlap spread, then a seeded tiebreak that
    deliberately replaces any alphabetical/lexicographic ordering of reviewer ids.

    ``initial_workload`` lets a caller (e.g. a layered engine that already committed some
    assignments from other selection layers) seed the workload counter before this core runs;
    omitted keys default to 0. It is never required for a fresh plan.

    Callers must ensure ``reviews_per_case <= len(reviewer_keys)`` (a case cannot get more distinct
    reviewers than exist) and ``reviewer_keys`` are unique; this function does not itself validate
    feasibility -- see ``infeasibility_reason``.
    """

    case_count = len(case_keys)
    if case_count == 0 or not reviewer_keys:
        return [[] for _ in case_keys]

    workload: dict[str, int] = {key: 0 for key in reviewer_keys}
    if initial_workload:
        for key, count in initial_workload.items():
            if key in workload:
                workload[key] = count
    pairwise_overlap: dict[tuple[str, str], int] = {}

    order = sorted(range(case_count), key=lambda i: _stable_random(seed, f"case:{case_keys[i]}"))
    result: list[list[str]] = [[] for _ in range(case_count)]
    for case_index in order:
        case_key = case_keys[case_index]
        chosen: list[str] = []
        for _ in range(reviews_per_case):
            best_candidate: str | None = None
            best_priority: tuple[int, int, float] | None = None
            for reviewer_key in reviewer_keys:
                if reviewer_key in chosen:
                    continue
                overlap_sum = sum(
                    pairwise_overlap.get(_pair_key(reviewer_key, other), 0) for other in chosen
                )
                priority = (
                    workload[reviewer_key],
                    overlap_sum,
                    _stable_random(seed, f"case:{case_key}:reviewer:{reviewer_key}"),
                )
                if best_priority is None or priority < best_priority:
                    best_priority = priority
                    best_candidate = reviewer_key
            if best_candidate is None:
                # Caller violated the documented precondition (reviews_per_case >
                # len(reviewer_keys)).
                raise ValueError("reviews_per_case exceeds the number of available reviewer_keys")
            chosen.append(best_candidate)
        for reviewer_key in chosen:
            workload[reviewer_key] += 1
        for left, right in combinations(chosen, 2):
            pair = _pair_key(left, right)
            pairwise_overlap[pair] = pairwise_overlap.get(pair, 0) + 1
        result[case_index] = chosen

    return result


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _stable_random(seed: str, key: str) -> float:
    """Deterministic, order-independent pseudo-randomness derived from a SHA-256 digest.

    Matches the pattern already used by ``review.allocation.planner.AllocationPlanner`` so both
    allocation paths get seeded reproducibility without ``random.Random`` (flagged by bandit
    B311 as unsuitable for security purposes -- neither use is security-sensitive, but a shared
    non-flagged pattern is simpler than auditing a suppression).
    """

    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
