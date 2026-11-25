"""Opaque keyset-cursor codec and page-size bounds shared by list endpoints.

The cursor is an opaque, URL-safe base64 of a small JSON keyset payload. It never exposes raw
database internals beyond the ordering keys already returned to the client, and an unparseable or
non-object cursor fails closed with a stable ``cursor_invalid`` problem.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from review_platform.common.errors import APIError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def encode_cursor(values: Mapping[str, Any]) -> str:
    """Serialise a keyset payload into an opaque, URL-safe cursor token."""

    raw = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Decode a cursor token back into its keyset payload, or ``None`` for the first page."""

    if cursor is None:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        value = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, TypeError) as exc:
        raise APIError(
            422,
            "cursor_invalid",
            "Invalid cursor",
            "The cursor is invalid.",
        ) from exc
    if not isinstance(value, dict):
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.")
    return value
