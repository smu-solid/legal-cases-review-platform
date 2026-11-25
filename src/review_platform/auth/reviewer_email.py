"""Reviewer invite email validation.

Two checks, applied at the single reviewer-invite choke point
(``roster.provision_reviewer_roster_entry``):"""

from __future__ import annotations

from collections.abc import Sequence

from email_validator import EmailNotValidError, validate_email

from review_platform.common.errors import APIError
from review_platform.security import normalize_email


def validate_reviewer_email(email: str, *, allowed_domains: Sequence[str] = ()) -> str:
    """Return the normalized reviewer email, or raise a 422 ``APIError``.

    ``allowed_domains`` is matched case-insensitively against the address domain; an empty sequence
    disables the domain check.
    """

    try:
        # Syntax validation only. ``test_environment`` disables DNS deliverability checks *and*
        # permits reserved/special-use domains (e.g. ``example.test`` in dev/CI fixtures) -- the
        # Google-domain allow-list below, not email_validator's deliverability policy, is the real
        # production gate on which domains may be invited.
        validated = validate_email(email, check_deliverability=False, test_environment=True)
    except EmailNotValidError as exc:
        raise APIError(
            422,
            "invalid_reviewer_email",
            "Invalid email",
            "Enter a valid email address.",
        ) from exc
    normalized = normalize_email(validated.normalized)
    allowed = {domain.strip().casefold() for domain in allowed_domains if domain.strip()}
    if allowed and normalized.rsplit("@", 1)[-1] not in allowed:
        raise APIError(
            422,
            "reviewer_email_domain_not_allowed",
            "Email domain not allowed",
            "Invite an email on an approved sign-in domain.",
        )
    return normalized
