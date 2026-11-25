"""Reviewer invite email validation: RFC validity + optional Google-domain allow-list."""

from __future__ import annotations

import pytest

from review_platform.auth.reviewer_email import validate_reviewer_email
from review_platform.common.errors import APIError

pytestmark = pytest.mark.no_db


def test_valid_email_is_normalized() -> None:
    assert validate_reviewer_email("Reviewer.One@Gmail.com") == "reviewer.one@gmail.com"


@pytest.mark.parametrize("bad", ["not-an-email", "no-domain@", "@no-local.com", "a b@x.com", ""])
def test_rfc_invalid_email_is_rejected(bad: str) -> None:
    with pytest.raises(APIError) as exc:
        validate_reviewer_email(bad)
    assert exc.value.status == 422
    assert exc.value.code == "invalid_reviewer_email"


def test_empty_allow_list_imposes_no_domain_restriction() -> None:
    # Local/CI seeding uses @example.test; an empty allow-list must not reject it.
    assert validate_reviewer_email("dev@example.test", allowed_domains=()) == "dev@example.test"


def test_domain_on_allow_list_is_accepted_case_insensitively() -> None:
    assert (
        validate_reviewer_email("Rev@Example.edu", allowed_domains=("gmail.com", "example.edu"))
        == "rev@example.edu"
    )


def test_domain_off_allow_list_is_rejected() -> None:
    with pytest.raises(APIError) as exc:
        validate_reviewer_email("rev@outlook.com", allowed_domains=("gmail.com", "example.edu"))
    assert exc.value.status == 422
    assert exc.value.code == "reviewer_email_domain_not_allowed"
