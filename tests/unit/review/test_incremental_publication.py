from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from review_platform.review.allocation import incremental_publication as publication
from review_platform.review.models import Assignment, AssignmentPlan

pytestmark = pytest.mark.no_db

_TENANT_ID = uuid.UUID(int=1)
_RUN_ID = uuid.UUID(int=2)
_LEASE = datetime(2030, 1, 1, tzinfo=UTC)


def _id(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


def _plan(index: int, unit: int, reviewer: int, kind: str = "new") -> AssignmentPlan:
    return AssignmentPlan(
        id=_id(1_000_000 + index),
        tenant_id=_TENANT_ID,
        allocation_run_id=_RUN_ID,
        review_unit_id=_id(10_000 + unit),
        reviewer_id=_id(20_000 + reviewer),
        status="planned",
        selection_layer="unique",
        overlap_group_key=None,
        window_index=None,
        plan_metadata_json={"movement_kind": kind, "movement_reason": "test"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(microseconds=index),
    )


def _assignment(index: int, unit: int, reviewer: int, status: str = "claimed") -> Assignment:
    return Assignment(
        id=_id(2_000_000 + index),
        tenant_id=_TENANT_ID,
        review_unit_id=_id(10_000 + unit),
        reviewer_id=_id(20_000 + reviewer),
        status=status,
        claimed_at=datetime(2025, 1, 1, tzinfo=UTC),
        lease_expires_at=datetime(2025, 2, 1, tzinfo=UTC),
    )


def _publish_batch(
    plans: list[AssignmentPlan],
    *,
    sources_by_target: dict[publication.AssignmentKey, tuple[uuid.UUID, ...]] | None = None,
    source_assignments: dict[publication.AssignmentKey, Assignment] | None = None,
    target_assignments: dict[publication.AssignmentKey, Assignment] | None = None,
) -> tuple[MagicMock, list[publication.AssignmentKey], list[publication.AssignmentKey]]:
    session = MagicMock(spec=Session)
    new_pairs: list[publication.AssignmentKey] = []
    moved_pairs: list[publication.AssignmentKey] = []
    publication._publish_batch(
        cast(Session, session),
        tenant_id=_TENANT_ID,
        plans=plans,
        lease_expires=_LEASE,
        sources_by_target=sources_by_target or {},
        source_assignments=source_assignments or {},
        target_assignments=target_assignments or {},
        new_pairs=new_pairs,
        moved_pairs=moved_pairs,
    )
    return session, new_pairs, moved_pairs


def test_new_assignment_is_created_once_and_linked_after_assignment_flush() -> None:
    plan = _plan(1, 1, 1)

    session, new_pairs, moved_pairs = _publish_batch([plan])

    assert new_pairs == [(plan.reviewer_id, plan.review_unit_id)]
    assert moved_pairs == []
    created = session.add_all.call_args.args[0]
    assert len(created) == 1
    assert created[0].status == "claimed"
    assert plan.assignment_id == created[0].id
    assert plan.status == "published"
    assert session.flush.call_count == 2


@pytest.mark.parametrize("target_status", ["claimed", "submitted", "revision_requested"])
def test_moved_plan_releases_source_before_preserving_existing_live_target(
    target_status: str,
) -> None:
    plan = _plan(1, 1, 2, "moved")
    source = _assignment(1, 1, 1)
    target = _assignment(2, 1, 2, target_status)
    original_claimed_at = target.claimed_at
    original_lease = target.lease_expires_at

    session, new_pairs, moved_pairs = _publish_batch(
        [plan],
        sources_by_target={(plan.review_unit_id, plan.reviewer_id): (source.reviewer_id,)},
        source_assignments={(source.review_unit_id, source.reviewer_id): source},
        target_assignments={(target.review_unit_id, target.reviewer_id): target},
    )

    assert source.status == "released"
    assert target.status == target_status
    assert target.claimed_at == original_claimed_at
    assert target.lease_expires_at == original_lease
    assert plan.assignment_id == target.id
    assert new_pairs == []
    assert moved_pairs == [(target.reviewer_id, target.review_unit_id)]
    session.add_all.assert_not_called()


def test_released_target_is_revived_in_place_for_returning_reviewer() -> None:
    plan = _plan(1, 1, 2)
    target = _assignment(2, 1, 2, "released")
    original_id = target.id

    session, new_pairs, _ = _publish_batch(
        [plan], target_assignments={(target.review_unit_id, target.reviewer_id): target}
    )

    assert target.id == original_id
    assert target.status == "claimed"
    assert target.lease_expires_at == _LEASE
    assert target.claimed_at > datetime(2025, 1, 1, tzinfo=UTC)
    assert plan.assignment_id == original_id
    assert new_pairs == []
    session.add_all.assert_not_called()


@pytest.mark.parametrize("source_status", ["submitted", "revision_requested", "released"])
def test_nonclaimed_source_work_is_never_released(source_status: str) -> None:
    plan = _plan(1, 1, 2, "moved")
    source = _assignment(1, 1, 1, source_status)

    _publish_batch(
        [plan],
        sources_by_target={(plan.review_unit_id, plan.reviewer_id): (source.reviewer_id,)},
        source_assignments={(source.review_unit_id, source.reviewer_id): source},
    )

    assert source.status == source_status


def test_same_reviewer_source_and_target_is_not_released_or_duplicated() -> None:
    plan = _plan(1, 1, 1, "moved")
    existing = _assignment(1, 1, 1)
    key = (existing.review_unit_id, existing.reviewer_id)

    session, new_pairs, moved_pairs = _publish_batch(
        [plan],
        sources_by_target={key: (existing.reviewer_id,)},
        source_assignments={key: existing},
        target_assignments={key: existing},
    )

    assert existing.status == "claimed"
    assert plan.assignment_id == existing.id
    assert new_pairs == []
    assert moved_pairs == [(existing.reviewer_id, existing.review_unit_id)]
    session.add_all.assert_not_called()


def test_sources_are_attributed_to_exact_target_with_multiple_targets() -> None:
    target_a = _plan(1, 1, 3, "moved")
    target_b = _plan(2, 1, 4, "moved")
    source_a = _assignment(1, 1, 1)
    source_b = _assignment(2, 1, 2)

    _, _, moved_pairs = _publish_batch(
        [target_a, target_b],
        sources_by_target={
            (target_a.review_unit_id, target_a.reviewer_id): (source_a.reviewer_id,),
            (target_b.review_unit_id, target_b.reviewer_id): (source_b.reviewer_id,),
        },
        source_assignments={
            (source_a.review_unit_id, source_a.reviewer_id): source_a,
            (source_b.review_unit_id, source_b.reviewer_id): source_b,
        },
    )

    assert source_a.status == source_b.status == "released"
    assert moved_pairs == [
        (target_a.reviewer_id, target_a.review_unit_id),
        (target_b.reviewer_id, target_b.review_unit_id),
    ]


def test_multiple_sources_for_one_target_are_all_released() -> None:
    plan = _plan(1, 1, 3, "moved")
    sources = [_assignment(index, 1, index) for index in (1, 2)]

    _publish_batch(
        [plan],
        sources_by_target={
            (plan.review_unit_id, plan.reviewer_id): tuple(row.reviewer_id for row in sources)
        },
        source_assignments={(row.review_unit_id, row.reviewer_id): row for row in sources},
    )

    assert [row.status for row in sources] == ["released", "released"]


def test_new_moved_collision_uses_collapsed_moved_plan_and_keeps_all_sources() -> None:
    plan = _plan(1, 1, 3, "moved")
    sources = [_assignment(index, 1, index) for index in (1, 2)]

    session, new_pairs, moved_pairs = _publish_batch(
        [plan],
        sources_by_target={
            (plan.review_unit_id, plan.reviewer_id): tuple(row.reviewer_id for row in sources)
        },
        source_assignments={(row.review_unit_id, row.reviewer_id): row for row in sources},
    )

    assert [row.status for row in sources] == ["released", "released"]
    assert new_pairs == []
    assert moved_pairs == [(plan.reviewer_id, plan.review_unit_id)]
    assert len(session.add_all.call_args.args[0]) == 1


def test_prefetch_statements_are_run_scoped_and_have_no_expanding_id_list() -> None:
    statements = [
        publication._planned_entries,
        publication._movement_sources,
        publication._source_assignments,
        publication._target_assignments,
    ]
    session = MagicMock(spec=Session)
    session.execute.return_value.all.return_value = []

    for loader in statements:
        loader(cast(Session, session), tenant_id=_TENANT_ID, run_id=_RUN_ID)

    issued = [call.args[0] for call in session.scalars.call_args_list]
    issued += [call.args[0] for call in session.execute.call_args_list]
    assert len(issued) == 4
    for statement in issued:
        compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        sql = str(compiled).lower()
        assert "tenant_id" in sql
        assert "allocation_run_id" in sql
        assert " in (__[postcompile" not in sql
        assert len(compiled.params) <= 5


def test_publication_flushes_twice_per_5000_plan_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    plans = [_plan(index, index, 1) for index in range(1, 5_002)]
    monkeypatch.setattr(publication, "_planned_entries", lambda *_args, **_kwargs: plans)
    monkeypatch.setattr(publication, "_movement_sources", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(publication, "_source_assignments", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(publication, "_target_assignments", lambda *_args, **_kwargs: {})
    session = MagicMock(spec=Session)

    new_pairs, moved_pairs = publication.publish_incremental_assignments(
        cast(Session, session), tenant_id=_TENANT_ID, run_id=_RUN_ID
    )

    assert len(new_pairs) == 5_001
    assert moved_pairs == []
    assert [len(call.args[0]) for call in session.add_all.call_args_list] == [5_000, 1]
    assert session.flush.call_count == 4
    session.commit.assert_not_called()


def test_later_publication_batch_failure_does_not_commit_first_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = [_plan(index, index, 1) for index in range(1, 5_002)]
    monkeypatch.setattr(publication, "_planned_entries", lambda *_args, **_kwargs: plans)
    monkeypatch.setattr(publication, "_movement_sources", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(publication, "_source_assignments", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(publication, "_target_assignments", lambda *_args, **_kwargs: {})
    session = MagicMock(spec=Session)
    session.flush.side_effect = [None, None, RuntimeError("later batch failed")]

    with pytest.raises(RuntimeError, match="later batch failed"):
        publication.publish_incremental_assignments(
            cast(Session, session), tenant_id=_TENANT_ID, run_id=_RUN_ID
        )

    assert session.flush.call_count == 3
    session.commit.assert_not_called()


def test_empty_plan_uses_one_query_and_no_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication, "_planned_entries", lambda *_args, **_kwargs: [])
    session = MagicMock(spec=Session)

    assert publication.publish_incremental_assignments(
        cast(Session, session), tenant_id=_TENANT_ID, run_id=_RUN_ID
    ) == ([], [])
    session.flush.assert_not_called()
    session.commit.assert_not_called()
