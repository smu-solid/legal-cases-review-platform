"""Deterministic case-selection strategies for campaign subject pools.

Selection ranks eligible review subjects for a campaign before allocation, so an admin can choose
*which* cases to review — not only how reviewers overlap on them. Two strategies are purely local
and always available:

- ``sequential`` — stable id order (the historical default);
- ``random`` — seeded, reproducible shuffle.

The two citation-hub strategies rank cases by their inbound or outbound citation degree:

- ``citation_in_hub`` — cases cited by many other cases (inbound degree);
- ``citation_out_hub`` — cases citing many other cases (outbound degree)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from review_platform.review.allocation.eligible_units import EligibleUnit

CaseSelectionStrategy = Literal[
    "sequential",
    "random",
    "citation_in_hub",
    "citation_out_hub",
]

CITATION_METRICS_KEY = "citation_metrics"
INBOUND_METRIC = "inbound_count"
OUTBOUND_METRIC = "outbound_count"

# Default seed keeps ``random`` selection reproducible when the caller omits an explicit seed.
DEFAULT_SELECTION_SEED = "case-selection/v1"

_HUB_METRIC: dict[CaseSelectionStrategy, str] = {
    "citation_in_hub": INBOUND_METRIC,
    "citation_out_hub": OUTBOUND_METRIC,
}


def citation_metric(unit: EligibleUnit, metric: str) -> int | None:
    """Return a non-negative citation count from the subject namespace, or ``None`` if absent.

    Fails closed on any malformed value (missing block, non-dict, boolean, negative, non-integer):
    a missing metric must never be silently coerced into a real-looking count.
    """

    block = unit.citation_metrics
    if not isinstance(block, dict):
        return None
    value = block.get(metric)
    # ``bool`` is an ``int`` subclass; reject it so ``True`` cannot masquerade as a count of 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def subject_metrics(unit: EligibleUnit) -> dict[str, float]:
    """Planner-facing metric map for hub scoring; empty when no citation metrics are exported."""

    metrics: dict[str, float] = {}
    for metric in (INBOUND_METRIC, OUTBOUND_METRIC):
        value = citation_metric(unit, metric)
        if value is not None:
            metrics[metric] = float(value)
    return metrics


@dataclass(frozen=True, slots=True)
class SubjectSelection:
    """Ordered eligible units plus a truthful account of citation-metric availability."""

    units: list[EligibleUnit]
    metrics_available: bool
    diagnostic: str | None


def _stable_random(subject_id: str, random_seed: str) -> float:
    digest = hashlib.sha256(f"{random_seed}:{subject_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def rank_subjects(
    units: list[EligibleUnit],
    *,
    strategy: CaseSelectionStrategy,
    random_seed: str,
) -> SubjectSelection:
    """Order eligible ``(unit, subject)`` pairs by the requested strategy.

    ``units`` is assumed to arrive in stable id order (the sequential baseline). Hub
    strategies rank by citation degree descending, seeded-random within ties. If no
    subject carries the metric the order is left sequential and ``metrics_available`` is
    ``False`` so callers do not mistake a fallback ordering for a real hub ranking."""

    if strategy == "sequential":
        return SubjectSelection(units=list(units), metrics_available=True, diagnostic=None)
    if strategy == "random":
        ordered = sorted(
            units,
            key=lambda unit: _stable_random(str(unit.review_subject_id), random_seed),
        )
        return SubjectSelection(units=ordered, metrics_available=True, diagnostic=None)

    metric = _HUB_METRIC[strategy]
    scored = [(unit, citation_metric(unit, metric)) for unit in units]
    present = sum(value is not None for _, value in scored)
    if present == 0:
        return SubjectSelection(
            units=list(units),
            metrics_available=False,
            diagnostic="citation_metrics_unavailable",
        )
    ordered = sorted(
        units,
        key=lambda unit: (
            -(citation_metric(unit, metric) or 0),
            _stable_random(str(unit.review_subject_id), random_seed),
            str(unit.review_subject_id),
        ),
    )
    diagnostic = None if present == len(scored) else "citation_metrics_partial"
    return SubjectSelection(units=ordered, metrics_available=True, diagnostic=diagnostic)
