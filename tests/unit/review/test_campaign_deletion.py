from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from review_platform.review.case_pool import campaign_has_started_work


@pytest.mark.no_db
def test_saved_work_check_does_not_expand_large_assignment_id_list() -> None:
    session = MagicMock(spec=Session)
    assignment = (uuid.uuid4(), "claimed")
    session.execute.return_value = [assignment] * 65_536
    session.scalar.side_effect = [None, None, None]

    assert not campaign_has_started_work(
        session,
        tenant_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
    )

    assert session.scalar.call_count == 3
    for call in session.scalar.call_args_list[1:]:
        statement = str(call.args[0])
        assert "JOIN review_platform.assignments" in statement
        assert "JOIN review_platform.review_units" in statement
        assert "assignment_id IN" not in statement


@pytest.mark.no_db
def test_reviewer_added_draft_counts_as_started_campaign_work() -> None:
    session = MagicMock(spec=Session)
    session.execute.return_value = [(uuid.uuid4(), "claimed")]
    session.scalar.return_value = uuid.uuid4()
    assert campaign_has_started_work(session, tenant_id=uuid.uuid4(), campaign_id=uuid.uuid4())
    assert "reviewer_added_proposals" in str(session.scalar.call_args.args[0])
