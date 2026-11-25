"""Indexed subject identity expressions shared by import and pool queries.

Attribute keys are repository-owned constants, never request-provided SQL identifiers.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import literal_column
from sqlalchemy.sql.elements import ColumnElement

from review_platform.review.models import ReviewSubject


def subject_attribute(key: str) -> ColumnElement[str]:
    """The indexed STORED column for the two hot keys (usable under FORCE RLS, unlike a ``->>``
    expression index); otherwise ``attributes_json ->> '<key>'`` with the key inlined."""

    if key == "logical_external_item_key":
        return cast("ColumnElement[str]", ReviewSubject.logical_external_item_key)
    if key == "snapshot_local_case_external_id":
        return cast("ColumnElement[str]", ReviewSubject.snapshot_local_case_external_id)
    return cast(
        "ColumnElement[str]",
        ReviewSubject.attributes_json.op("->>")(literal_column(f"'{key}'")),
    )
