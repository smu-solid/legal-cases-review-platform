"""Shared case-heading projection for reviewer and adjudicator queues."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from review_platform.review.models import Candidate, ReviewSubject, ReviewUnit
from review_platform.review.relation_display import (
    extracted_value,
    is_neutral_citation_field,
    is_reported_citation_field,
    is_title_field,
)


@dataclass(frozen=True)
class CaseDisplay:
    case_title: str
    neutral_citation_display: str | None
    reported_citation_display: str | None


def case_display(
    rows: Iterable[tuple[ReviewUnit, ReviewSubject]],
    *,
    candidates_by_unit: Mapping[uuid.UUID, Candidate],
) -> CaseDisplay:
    """Derive the same complete, display-safe case heading for every workflow queue."""

    case_rows = list(rows)
    if not case_rows:
        raise ValueError("A case display requires at least one review unit.")
    case_title: str | None = None
    neutral_citation_display: str | None = None
    reported_citation_display: str | None = None
    for unit, subject in case_rows:
        if case_title is None and is_title_field(unit.field_name, unit.safe_field_label):
            case_title = subject.display_title
        elif neutral_citation_display is None and is_neutral_citation_field(
            unit.field_name, unit.safe_field_label
        ):
            neutral_citation_display, _ = extracted_value(
                candidates_by_unit.get(unit.id), fallback=subject.display_title
            )
        elif reported_citation_display is None and is_reported_citation_field(
            unit.field_name, unit.safe_field_label
        ):
            reported_citation_display, _ = extracted_value(
                candidates_by_unit.get(unit.id), fallback=subject.display_title
            )
    return CaseDisplay(
        case_title=case_title or case_rows[0][1].display_title,
        neutral_citation_display=neutral_citation_display,
        reported_citation_display=reported_citation_display,
    )
