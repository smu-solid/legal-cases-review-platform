"""Caller-personalized adjudication progress arithmetic."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from review_platform.review.adjudication_campaign_projections import _case_status
from review_platform.review.schemas import AdjudicationResponsibilityProgress

pytestmark = pytest.mark.no_db


def test_submitted_waived_pending_future_and_not_required_are_disjoint() -> None:
    progress = AdjudicationResponsibilityProgress(
        total_scoped_fields=10,
        personal_responsibility_fields=8,
        completed_responsibility_fields=5,
        submitted_fields=3,
        waived_fields=2,
        pending_fields=1,
        future_eligible_fields=2,
        not_required_fields=2,
    )
    assert progress.completed_responsibility_fields <= progress.personal_responsibility_fields


@pytest.mark.parametrize(
    "changes",
    [
        {"completed_responsibility_fields": 9},
        {"personal_responsibility_fields": 7},
        {"total_scoped_fields": 9},
    ],
)
def test_invalid_progress_partitions_are_rejected(changes: dict[str, int]) -> None:
    values = {
        "total_scoped_fields": 10,
        "personal_responsibility_fields": 8,
        "completed_responsibility_fields": 5,
        "submitted_fields": 3,
        "waived_fields": 2,
        "pending_fields": 1,
        "future_eligible_fields": 2,
        "not_required_fields": 2,
        **changes,
    }
    with pytest.raises(ValidationError):
        AdjudicationResponsibilityProgress(**values)


def test_fully_not_required_has_no_personal_denominator() -> None:
    progress = AdjudicationResponsibilityProgress(
        total_scoped_fields=4,
        personal_responsibility_fields=0,
        completed_responsibility_fields=0,
        submitted_fields=0,
        waived_fields=0,
        pending_fields=0,
        future_eligible_fields=0,
        not_required_fields=4,
    )
    assert progress.not_required_fields == progress.total_scoped_fields


def test_zero_personal_responsibility_is_not_finished() -> None:
    status, completion, code, reason, anchor, mode = _case_status(
        submitted=0,
        waived=0,
        pending=0,
        future=0,
        edit_anchor=None,
        view_anchor=None,
    )
    assert (status, completion, code) == ("not_required", "not_required", "not_required")
    assert reason == "No adjudication is assigned to you for this case"
    assert anchor is None
    assert mode is None
