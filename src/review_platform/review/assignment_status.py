"""What counts as a *live* assignment, in one place.

A ``released`` assignment is a review unit an incremental rebalance moved AWAY from a reviewer
(``allocation/incremental_publish.py`` flips the previous holder's row rather than deleting it, so
the move stays auditable). The row is history: the reviewer cannot act on it, it is excluded from
their queue, and it must not be counted as work they hold.

Every read path that counts or filters assignments therefore needs the same ``!= 'released'``
predicate. Spreading that literal across the query sites has regressed twice -- once when the
reviewer-workload totals counted released rows (a reviewer read 237 against a real 220), and again
when the per-case progress table did (a repaired case read "0/3" in a two-reviews-per-case campaign
and could never be reported complete). Both were the same omission in a different query.

Import these helpers rather than writing the comparison inline;
``test_live_assignment_predicate.py`` fails the build if the raw literal reappears in a query
module.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, case, func
from sqlalchemy.sql._typing import _ColumnExpressionArgument

from review_platform.review.models import Assignment

RELEASED_STATUS = "released"


def assignment_is_live() -> ColumnElement[bool]:
    """True for assignments a reviewer still holds.

    Written as ``!= 'released'`` rather than ``IN ('claimed', 'submitted')`` so that
    ``revision_requested`` -- also live work, and also actionable by the reviewer -- stays inside
    every total without each call site having to remember it.
    """

    return Assignment.status != RELEASED_STATUS


def assignment_is_released() -> ColumnElement[bool]:
    """True for the audit rows a rebalance left behind. The exact complement of ``is_live``."""

    return Assignment.status == RELEASED_STATUS


def count_live(
    column: _ColumnExpressionArgument[Any], *, distinct: bool = False
) -> ColumnElement[int]:
    """``COUNT(column)`` over live assignment rows only.

    Pass ``distinct=True`` for the reviewer-identity counts ("how many reviewers hold this case"),
    where the same reviewer legitimately appears once per unit.
    """

    counted = case((assignment_is_live(), column))
    return func.count(counted.distinct() if distinct else counted)


def count_released(column: _ColumnExpressionArgument[Any]) -> ColumnElement[int]:
    """``COUNT(column)`` over released rows only -- reported separately so nothing is hidden."""

    return func.count(case((assignment_is_released(), column)))
