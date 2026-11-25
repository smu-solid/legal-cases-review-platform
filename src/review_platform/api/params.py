"""Shared HTTP parameter and header helpers."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header, Query, Response

from review_platform.common.errors import APIError
from review_platform.common.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

ETAG_PATTERN = re.compile(r'^"([1-9][0-9]*)"$')
LOCK_VERSION_RESPONSE_HEADERS = {
    "ETag": {
        "description": (
            "Quoted strong integer tag matching the response body lock_version. "
            'Send it back as If-Match, for example "3", on the next mutation.'
        ),
        "schema": {"type": "string", "pattern": r'^"[1-9][0-9]*"$'},
    },
    "Cache-Control": {
        "description": "Reviewer and source/evidence responses are private and never cacheable.",
        "schema": {"type": "string", "const": "no-store"},
    },
}

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]
IfMatch = Annotated[str, Header(alias="If-Match")]

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
PageCursor = Annotated[str | None, Query(min_length=1, max_length=500)]
DEFAULT_LIMIT = DEFAULT_PAGE_SIZE


def expected_version(value: str) -> int:
    match = ETAG_PATTERN.fullmatch(value)
    if match is None:
        raise APIError(
            422,
            "if_match_invalid",
            "Invalid If-Match",
            'If-Match must contain one strong integer ETag such as "1".',
        )
    return int(match.group(1))


def format_strong_etag(version: int) -> str:
    return f'"{version}"'


def set_lock_version_etag(response: Response, version: int) -> None:
    """Set the strong ``ETag`` response header from a resource lock version.

    Centralises the header name and the strong-ETag convention that reviewer mutation and read
    routes share, so the concurrency contract cannot drift between endpoints.
    """

    response.headers["ETag"] = format_strong_etag(version)
