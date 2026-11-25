from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from review_platform.review.allocation.incremental_persistence import (
    INCREMENTAL_MOVEMENT_BATCH_SIZE,
    persist_incremental_movement_plans,
)
from review_platform.review.models import IncrementalMovementPlan

pytestmark = pytest.mark.no_db


def _movements(count: int) -> list[IncrementalMovementPlan]:
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    return [
        IncrementalMovementPlan(
            tenant_id=tenant_id,
            allocation_run_id=run_id,
            subject_id=uuid.uuid4(),
            from_reviewer_id=None,
            to_reviewer_id=reviewer_id,
            movement_kind="new",
            movement_reason="coverage_gap",
        )
        for _ in range(count)
    ]


def test_movement_plans_flush_and_expunge_in_bounded_batches() -> None:
    session = MagicMock(spec=Session)
    movements = _movements(INCREMENTAL_MOVEMENT_BATCH_SIZE * 2 + 1)

    count = persist_incremental_movement_plans(cast(Session, session), movements)

    assert count == len(movements)
    assert [len(call.args[0]) for call in session.add_all.call_args_list] == [5_000, 5_000, 1]
    assert session.flush.call_count == 3
    assert [call.args[0] for call in session.expunge.call_args_list] == movements
    session.commit.assert_not_called()


def test_movement_plan_empty_input_is_a_noop() -> None:
    session = MagicMock(spec=Session)

    assert persist_incremental_movement_plans(cast(Session, session), []) == 0
    session.add_all.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_movement_plan_batch_failure_is_left_to_outer_transaction_rollback() -> None:
    session = MagicMock(spec=Session)
    session.flush.side_effect = [None, RuntimeError("second batch failed")]

    with pytest.raises(RuntimeError, match="second batch failed"):
        persist_incremental_movement_plans(
            cast(Session, session), _movements(5_001), batch_size=5_000
        )

    assert session.flush.call_count == 2
    session.commit.assert_not_called()


def test_movement_plan_batch_size_must_be_positive() -> None:
    session = MagicMock(spec=Session)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        persist_incremental_movement_plans(cast(Session, session), [], batch_size=0)
