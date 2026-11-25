from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from review_platform.review.campaign_materialization import _move_selected_units

pytestmark = pytest.mark.no_db

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_POOL_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_TARGET_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _RecordingSession:
    def __init__(
        self,
        selected_unit_ids: list[uuid.UUID],
        *,
        rowcounts: list[int] | None = None,
        fail_on_call: int | None = None,
    ) -> None:
        self._selected = set(selected_unit_ids)
        self._rowcounts = iter(rowcounts) if rowcounts is not None else None
        self._fail_on_call = fail_on_call
        self.batch_sizes: list[int] = []
        self.parameter_counts: list[int] = []

    def execute(self, statement: Any) -> _Result:
        call_number = len(self.batch_sizes) + 1
        if self._fail_on_call == call_number:
            raise RuntimeError("deliberate batch failure")
        compiled = statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"render_postcompile": True},
        )
        batch_size = sum(value in self._selected for value in compiled.params.values())
        self.batch_sizes.append(batch_size)
        self.parameter_counts.append(len(compiled.params))
        rowcount = next(self._rowcounts) if self._rowcounts is not None else batch_size
        return _Result(rowcount)


def _unit_ids(count: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=index + 10) for index in range(count)]


def _move(session: _RecordingSession, unit_ids: list[uuid.UUID]) -> int:
    return _move_selected_units(
        cast(Session, session),
        tenant_id=_TENANT_ID,
        pool_campaign_id=_POOL_ID,
        target_campaign_id=_TARGET_ID,
        required_reviews=3,
        selected_unit_ids=unit_ids,
    )


@pytest.mark.parametrize(
    ("unit_count", "expected_batches"),
    [
        (0, []),
        (1, [1]),
        (50_000, [50_000]),
        (50_001, [50_000, 1]),
        (65_530, [50_000, 15_530]),
        (100_000, [50_000, 50_000]),
    ],
)
def test_movement_batches_are_deterministic_and_parameter_safe(
    unit_count: int, expected_batches: list[int]
) -> None:
    unit_ids = _unit_ids(unit_count)
    session = _RecordingSession(unit_ids)

    assert _move(session, unit_ids) == unit_count
    assert session.batch_sizes == expected_batches
    assert all(parameter_count < 65_535 for parameter_count in session.parameter_counts)
    assert session.parameter_counts == [batch_size + 6 for batch_size in expected_batches]


def test_duplicate_selected_uuid_is_rejected_before_any_update() -> None:
    duplicate_id = uuid.uuid4()
    session = _RecordingSession([duplicate_id])

    with pytest.raises(RuntimeError, match="duplicate review-unit UUIDs"):
        _move(session, [duplicate_id, duplicate_id])

    assert session.batch_sizes == []


def test_total_affected_row_mismatch_is_rejected_across_batches() -> None:
    unit_ids = _unit_ids(50_001)
    session = _RecordingSession(unit_ids, rowcounts=[50_000, 0])

    with pytest.raises(RuntimeError, match="different number of units"):
        _move(session, unit_ids)

    assert session.batch_sizes == [50_000, 1]


def test_second_batch_failure_propagates_without_starting_a_third_statement() -> None:
    unit_ids = _unit_ids(100_000)
    session = _RecordingSession(unit_ids, fail_on_call=2)

    with pytest.raises(RuntimeError, match="deliberate batch failure"):
        _move(session, unit_ids)

    assert session.batch_sizes == [50_000]
