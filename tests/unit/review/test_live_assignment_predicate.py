"""The live-assignment predicate must have exactly one definition.

Counting ``released`` assignments as live work has regressed twice, each time in a query that had
simply been written without the filter (reviewer workload totals; then the per-case progress table
and the fully-complete rollup). Both were fixed by adding the same comparison in yet another place.

This guards the shared helper instead: production code outside ``assignment_status.py`` may not
compare ``Assignment.status`` against the ``released`` literal directly. A new read path either
imports the predicate or fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from review_platform.review.assignment_status import (
    assignment_is_live,
    assignment_is_released,
    count_live,
    count_released,
)
from review_platform.review.models import Assignment

_SRC = Path(__file__).resolve().parents[3] / "src" / "review_platform"
_OWNER = _SRC / "review" / "assignment_status.py"

# Assignment.status compared against the released literal, in either order, quoted either way.
_RAW_COMPARISON = re.compile(
    r"""Assignment\.status\s*[!=]=\s*['"]released['"]|['"]released['"]\s*[!=]=\s*Assignment\.status"""
)


# No allowlist by design. The pattern matches only a *column* comparison, so the places the literal
# legitimately appears are untouched: the CHECK constraint and wire enums declare it as a string,
# and the writers that retire a claim (``assignment.status = "released"``) assign rather than
# compare. Every remaining match is a query filter that should use the shared predicate.
def test_no_production_module_recreates_the_released_comparison() -> None:
    offenders = [
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if path != _OWNER
        and "migrations" not in path.parts
        and _RAW_COMPARISON.search(path.read_text())
    ]
    assert offenders == [], (
        "these modules compare Assignment.status to 'released' directly; import "
        "assignment_is_live()/count_live() from review.assignment_status instead: "
        f"{offenders}"
    )


def test_live_excludes_released_and_keeps_revision_requested() -> None:
    """The predicate is ``!= 'released'``, not ``IN ('claimed', 'submitted')``.

    ``revision_requested`` is live work the reviewer can still act on, so it must stay inside every
    total -- the distinction the wrong formulation would silently lose.
    """

    compiled = str(assignment_is_live().compile(compile_kwargs={"literal_binds": True}))
    assert "!=" in compiled
    assert "released" in compiled
    for live_status in ("claimed", "submitted", "revision_requested"):
        assert live_status not in compiled


def test_live_and_released_are_exact_complements() -> None:
    live = str(assignment_is_live().compile(compile_kwargs={"literal_binds": True}))
    released = str(assignment_is_released().compile(compile_kwargs={"literal_binds": True}))
    assert live == released.replace(" = ", " != ", 1)


def test_count_live_distinct_counts_each_reviewer_once() -> None:
    """``distinct=True`` is what makes "how many reviewers hold this case" correct.

    Without it the same reviewer counts once per unit, which is how the case progress cell came to
    read a reviewer count in the hundreds rather than 2.
    """

    plain = str(select(count_live(Assignment.reviewer_id)).compile())
    distinct = str(select(count_live(Assignment.reviewer_id, distinct=True)).compile())
    assert "DISTINCT" not in plain.upper()
    assert "DISTINCT" in distinct.upper()


def test_count_helpers_wrap_the_matching_predicate() -> None:
    live = str(select(count_live(Assignment.id)).compile(compile_kwargs={"literal_binds": True}))
    released = str(
        select(count_released(Assignment.id)).compile(compile_kwargs={"literal_binds": True})
    )
    assert "!=" in live and "!=" not in released
    assert str(func.count()).lower().startswith("count")


pytestmark = pytest.mark.no_db
