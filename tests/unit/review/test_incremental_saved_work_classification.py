from __future__ import annotations

import uuid
from typing import Any, NamedTuple, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from review_platform.review.allocation.incremental_inputs import (
    _IMMOVABILITY,
    AllocationIncrementalInputsMixin,
)
from review_platform.review.incremental_planner import (
    ExistingAssignment,
    IncrementalPlanner,
    IncrementalPolicy,
    IncrementalReviewer,
    MovementPolicy,
)

pytestmark = pytest.mark.no_db

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_CAMPAIGN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _AssignmentRow(NamedTuple):
    id: uuid.UUID
    review_unit_id: uuid.UUID
    reviewer_id: uuid.UUID
    status: str


class _Rows:
    def __init__(self, rows: list[_AssignmentRow]) -> None:
        self._rows = rows

    def all(self) -> list[_AssignmentRow]:
        return self._rows


class _RecordingSession:
    def __init__(
        self,
        rows: list[_AssignmentRow],
        answer_ids: set[uuid.UUID],
        annotation_ids: set[uuid.UUID],
    ) -> None:
        self.rows = rows
        self.saved_id_results = iter((answer_ids, annotation_ids))
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows(self.rows)

    def scalars(self, statement: Any) -> set[uuid.UUID]:
        self.statements.append(statement)
        return next(self.saved_id_results)


def _id(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


def _row(index: int, unit: int, reviewer: int, status: str = "claimed") -> _AssignmentRow:
    return _AssignmentRow(_id(1_000 + index), _id(10_000 + unit), _id(20_000 + reviewer), status)


def _reference_classification(
    rows: list[_AssignmentRow],
    *,
    eligible_units: set[uuid.UUID],
    case_by_unit: dict[uuid.UUID, str],
    saved_ids: set[uuid.UUID],
) -> list[ExistingAssignment]:
    """The previous per-assignment result, expressed without issuing its N+1 queries."""

    by_case_reviewer: dict[tuple[str, str], str] = {}
    for row in rows:
        if row.review_unit_id not in eligible_units:
            continue
        movement_class = (
            "submitted"
            if row.status == "submitted"
            else "draft"
            if row.id in saved_ids
            else "claimed"
        )
        key = (
            case_by_unit.get(row.review_unit_id, f"unit:{row.review_unit_id}"),
            str(row.reviewer_id),
        )
        previous = by_case_reviewer.get(key)
        if previous is None or _IMMOVABILITY[movement_class] > _IMMOVABILITY[previous]:
            by_case_reviewer[key] = movement_class
    return [
        ExistingAssignment(subject_id=case_id, reviewer_id=reviewer_id, movement_class=movement)  # type: ignore[arg-type]
        for (case_id, reviewer_id), movement in by_case_reviewer.items()
    ]


def _classify(
    rows: list[_AssignmentRow],
    *,
    answer_ids: set[uuid.UUID] | None = None,
    annotation_ids: set[uuid.UUID] | None = None,
    eligible_units: set[uuid.UUID] | None = None,
    case_by_unit: dict[uuid.UUID, str] | None = None,
) -> tuple[list[ExistingAssignment], _RecordingSession]:
    answer_ids = answer_ids or set()
    annotation_ids = annotation_ids or set()
    all_units = {row.review_unit_id for row in rows}
    eligible_units = all_units if eligible_units is None else eligible_units
    case_by_unit = case_by_unit or {
        unit_id: f"case-{index}" for index, unit_id in enumerate(sorted(eligible_units))
    }
    session = _RecordingSession(rows, answer_ids, annotation_ids)
    service = AllocationIncrementalInputsMixin("test-audit-key")
    actual = service._classify_existing_assignments(
        cast(Session, session),
        tenant_id=_TENANT_ID,
        campaign_id=_CAMPAIGN_ID,
        unit_ids=eligible_units,
        case_by_unit=case_by_unit,
    )
    expected = _reference_classification(
        rows,
        eligible_units=eligible_units,
        case_by_unit=case_by_unit,
        saved_ids=answer_ids | annotation_ids,
    )
    assert actual == expected
    return actual, session


@pytest.mark.parametrize(
    ("name", "rows", "answers", "annotations", "expected"),
    [
        ("untouched_claimed", [_row(1, 1, 1)], set(), set(), ["claimed"]),
        ("saved_answer", [_row(1, 1, 1)], {_id(1_001)}, set(), ["draft"]),
        ("annotation_revision", [_row(1, 1, 1)], set(), {_id(1_001)}, ["draft"]),
        ("both_saved_forms", [_row(1, 1, 1)], {_id(1_001)}, {_id(1_001)}, ["draft"]),
        ("submitted", [_row(1, 1, 1, "submitted")], set(), set(), ["submitted"]),
        ("revision_requested", [_row(1, 1, 1, "revision_requested")], set(), set(), ["claimed"]),
        ("removed_reviewer_untouched", [_row(1, 1, 9)], set(), set(), ["claimed"]),
        ("removed_reviewer_saved", [_row(1, 1, 9)], {_id(1_001)}, set(), ["draft"]),
        ("returning_reviewer", [_row(1, 1, 9)], set(), {_id(1_001)}, ["draft"]),
    ],
)
def test_set_based_classification_matches_previous_per_assignment_result(
    name: str,
    rows: list[_AssignmentRow],
    answers: set[uuid.UUID],
    annotations: set[uuid.UUID],
    expected: list[str],
) -> None:
    del name
    actual, session = _classify(rows, answer_ids=answers, annotation_ids=annotations)

    assert [item.movement_class for item in actual] == expected
    assert len(session.statements) == 3


def test_released_assignments_are_absent_from_the_live_campaign_rows() -> None:
    actual, session = _classify([])

    assert actual == []
    assert session.statements == []


def test_mixed_units_keep_exact_least_movable_precedence_for_each_reviewer() -> None:
    rows = [
        _row(1, 1, 1),
        _row(2, 2, 1),
        _row(3, 3, 1, "submitted"),
        _row(4, 1, 2),
        _row(5, 2, 2),
    ]
    case_by_unit = {row.review_unit_id: "mixed-case" for row in rows}

    actual, _session = _classify(
        rows,
        answer_ids={rows[1].id, rows[4].id},
        case_by_unit=case_by_unit,
    )

    assert actual == [
        ExistingAssignment(
            subject_id="mixed-case",
            reviewer_id=str(rows[0].reviewer_id),
            movement_class="submitted",
        ),
        ExistingAssignment(
            subject_id="mixed-case", reviewer_id=str(rows[3].reviewer_id), movement_class="draft"
        ),
    ]


def test_appended_and_out_of_scope_units_do_not_change_existing_inputs() -> None:
    eligible = {_id(10_001), _id(10_002)}
    rows = [_row(1, 1, 1), _row(2, 99, 2)]
    actual, _session = _classify(
        rows,
        answer_ids={rows[1].id},
        eligible_units=eligible,
        case_by_unit={_id(10_001): "old-case", _id(10_002): "appended-case"},
    )

    assert actual == [
        ExistingAssignment(
            subject_id="old-case", reviewer_id=str(rows[0].reviewer_id), movement_class="claimed"
        )
    ]


def test_campaign_and_tenant_scoped_statements_use_no_expanding_id_predicate() -> None:
    _actual, session = _classify([_row(1, 1, 1)])

    assert len(session.statements) == 3
    for statement in session.statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled).lower()
        assert "review_units" in sql
        assert "campaign_id" in sql
        assert "tenant_id" in sql
        assert " in (__[postcompile" not in sql
        assert len(compiled.params) <= 5


def test_query_count_is_constant_for_large_all_claimed_campaign() -> None:
    rows = [_row(index, index, (index % 7) + 1) for index in range(1, 20_001)]

    actual, session = _classify(rows)

    assert len(actual) == len(rows)
    assert len(session.statements) == 3


def test_exact_planner_output_is_unchanged_by_set_based_classification() -> None:
    rows = [_row(1, 1, 1), _row(2, 2, 1), _row(3, 1, 2), _row(4, 2, 2)]
    units = {row.review_unit_id for row in rows}
    case_by_unit = {
        rows[0].review_unit_id: "case-a",
        rows[1].review_unit_id: "case-b",
        rows[2].review_unit_id: "case-a",
        rows[3].review_unit_id: "case-b",
    }
    answers = {rows[1].id}
    actual, _session = _classify(
        rows,
        answer_ids=answers,
        eligible_units=units,
        case_by_unit=case_by_unit,
    )
    reference = _reference_classification(
        rows,
        eligible_units=units,
        case_by_unit=case_by_unit,
        saved_ids=answers,
    )
    reviewers = tuple(
        IncrementalReviewer(
            reviewer_id=str(_id(20_000 + index)),
            active=True,
            authorized=True,
            capacity_weight=1.0,
        )
        for index in (1, 2, 3)
    )
    policy = IncrementalPolicy(
        min_reviews_per_subject=2,
        max_workload_per_reviewer=None,
        movement_policy=MovementPolicy(
            allow_rebalance_unclaimed=True,
            allow_rebalance_claimed=True,
            allow_rebalance_draft=False,
        ),
        random_seed="step4-parity",
        allocation_policy_version="incremental/v1",
    )
    kwargs = {
        "subject_ids": ("case-a", "case-b", "appended-case"),
        "reviewers": reviewers,
        "policy": policy,
        "previous_reviewer_ids": tuple(item.reviewer_id for item in reviewers[:2]),
    }

    actual_preview = IncrementalPlanner().plan(existing_assignments=tuple(actual), **kwargs)  # type: ignore[arg-type]
    reference_preview = IncrementalPlanner().plan(existing_assignments=tuple(reference), **kwargs)  # type: ignore[arg-type]

    assert actual_preview == reference_preview
    assert actual_preview.movement_plan == reference_preview.movement_plan
    assert actual_preview.workload_summaries == reference_preview.workload_summaries
