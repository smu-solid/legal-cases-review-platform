from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from review_platform.review.allocation.plan_persistence import (
    ASSIGNMENT_PLAN_BATCH_SIZE,
    persist_assignment_plans,
)
from review_platform.review.models import AssignmentPlan

pytestmark = pytest.mark.no_db


def _plans(count: int) -> list[AssignmentPlan]:
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    return [
        AssignmentPlan(
            tenant_id=tenant_id,
            allocation_run_id=run_id,
            review_unit_id=uuid.uuid4(),
            reviewer_id=reviewer_id,
            status="planned",
            selection_layer="unique",
            overlap_group_key=None,
            window_index=None,
            plan_metadata_json={"ordinal": ordinal},
        )
        for ordinal in range(count)
    ]


def test_persist_assignment_plans_flushes_and_expunges_bounded_batches() -> None:
    session = MagicMock(spec=Session)
    plans = _plans(ASSIGNMENT_PLAN_BATCH_SIZE * 2 + 1)

    persisted_count = persist_assignment_plans(cast(Session, session), iter(plans))

    assert persisted_count == len(plans)
    assert [len(call.args[0]) for call in session.add_all.call_args_list] == [5_000, 5_000, 1]
    assert session.flush.call_count == 3
    assert session.expunge.call_count == len(plans)
    assert [call.args[0] for call in session.expunge.call_args_list] == plans
    session.commit.assert_not_called()


def test_persist_assignment_plans_preserves_final_flush_for_empty_input() -> None:
    session = MagicMock(spec=Session)

    assert persist_assignment_plans(cast(Session, session), []) == 0

    session.add_all.assert_not_called()
    session.flush.assert_called_once_with()
    session.expunge.assert_not_called()
    session.commit.assert_not_called()


def test_persist_assignment_plans_rejects_non_positive_batch_size() -> None:
    session = MagicMock(spec=Session)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        persist_assignment_plans(cast(Session, session), [], batch_size=0)
