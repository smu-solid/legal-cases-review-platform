"""Case identity helpers shared by adjudication queue, claim, and grouped reads."""

from __future__ import annotations

from typing import cast

from sqlalchemy.sql.elements import ColumnElement

from review_platform.review.models import ReviewSubject

CASE_ID_ATTRIBUTE = "snapshot_local_case_external_id"


def adjudication_case_id(subject: ReviewSubject) -> str:
    """Return the stable case id used to batch field-level adjudications.

    Real and current synthetic imports tag every field/relation subject with the case id. The
    subject-id fallback keeps legacy rows isolated instead of accidentally merging unrelated work.
    """

    value = subject.attributes_json.get(CASE_ID_ATTRIBUTE)
    return str(value) if value is not None else f"subject:{subject.id}"


def same_case_clause(subject: ReviewSubject) -> ColumnElement[bool]:
    """SQL predicate matching the durable case identity on an anchor subject."""

    value = subject.attributes_json.get(CASE_ID_ATTRIBUTE)
    if value is None:
        return ReviewSubject.id == subject.id
    return cast(
        ColumnElement[bool],
        ReviewSubject.attributes_json[CASE_ID_ATTRIBUTE].astext == str(value),
    )
