"""Transport-independent invariants for the reviewer-correction (revision) window."""

from __future__ import annotations

import pytest

from review_platform.common.errors import APIError
from review_platform.review.state_machine import (
    validate_revision_reopen,
    validate_revision_request,
)

pytestmark = pytest.mark.no_db


def test_request_revision_returns_trimmed_reason() -> None:
    assert (
        validate_revision_request(
            "submitted", "  please fix value  ", expected_version_matches=True
        )
        == "please fix value"
    )


def test_request_revision_rejects_stale_version() -> None:
    with pytest.raises(APIError) as caught:
        validate_revision_request("submitted", "fix", expected_version_matches=False)
    assert caught.value.status == 412
    assert caught.value.code == "precondition_failed"


@pytest.mark.parametrize("status", ["claimed", "released", "revision_requested"])
def test_request_revision_requires_submitted(status: str) -> None:
    with pytest.raises(APIError) as caught:
        validate_revision_request(status, "fix", expected_version_matches=True)
    assert caught.value.status == 409
    assert caught.value.code == "assignment_revision_not_requestable"


@pytest.mark.parametrize("reason", ["", "   "])
def test_request_revision_requires_nonblank_reason(reason: str) -> None:
    with pytest.raises(APIError) as caught:
        validate_revision_request("submitted", reason, expected_version_matches=True)
    assert caught.value.status == 422
    assert caught.value.code == "revision_reason_required"


def test_reopen_allows_revision_requested() -> None:
    assert validate_revision_reopen("revision_requested", expected_version_matches=True) is None


def test_reopen_rejects_stale_version() -> None:
    with pytest.raises(APIError) as caught:
        validate_revision_reopen("revision_requested", expected_version_matches=False)
    assert caught.value.status == 412
    assert caught.value.code == "precondition_failed"


@pytest.mark.parametrize("status", ["claimed", "submitted", "released"])
def test_reopen_rejects_non_revision_statuses(status: str) -> None:
    with pytest.raises(APIError) as caught:
        validate_revision_reopen(status, expected_version_matches=True)
    assert caught.value.status == 409
    assert caught.value.code == "assignment_revision_not_reopenable"
