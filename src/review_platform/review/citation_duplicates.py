"""Conservative citation comparison; independent of adjudication grouping."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from review_platform.common.errors import APIError, FieldProblem
from review_platform.review.proposal_matching import normalized_proposal_value as normalize
from review_platform.review.schemas.citation_duplicates import (
    CitationConflict,
    CitationDuplicateCheck,
)

SpanKey = tuple[str, str, int, int]


def _normalize_duplicate_value(value: str) -> str:
    return normalize(value).strip(" .,")


@dataclass
class CitationItem:
    id: uuid.UUID
    value: str
    spans: set[SpanKey] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    identity: str | None = None
    possible_aliases: set[str] = field(default_factory=set)
    incomplete: bool = False
    submitted: bool = False
    authored: bool = False
    reviewer_added: bool = False
    provenance_text: tuple[str, ...] = ()
    original_values: set[str] = field(default_factory=set)

    def values(self) -> set[str]:
        return {normalize(v) for v in {self.value, *self.aliases} if v.strip()}

    def duplicate_values(self) -> set[str]:
        values = set(self.original_values)
        if not self.incomplete:
            values.update((self.value, *self.aliases))
        # A reporter field can contain several parallel citations separated by semicolons.
        return {
            normalized
            for value in values
            for part in (value, *value.split(";"))
            if (normalized := _normalize_duplicate_value(part))
        }


def classify(left: CitationItem, right: CitationItem) -> tuple[Literal["confirmed"], str] | None:
    if left.reviewer_added or right.reviewer_added:
        addition, existing = (left, right) if left.reviewer_added else (right, left)
        texts = addition.duplicate_values() | {
            normalized
            for text in addition.provenance_text
            if (normalized := _normalize_duplicate_value(text))
        }
        if any(
            value in text or text in value
            for value in existing.duplicate_values()
            for text in texts
        ):
            return (
                "confirmed",
                "Citation value matches the normalized value or marked provenance by substring",
            )
        return None
    if left.incomplete or right.incomplete:
        return None
    if (
        normalize(left.value)
        and normalize(left.value) == normalize(right.value)
        and left.spans
        and left.spans == right.spans
    ):
        return "confirmed", "Same normalized value and complete marked provenance"
    return None


def check_duplicates(current: CitationItem, others: list[CitationItem]) -> CitationDuplicateCheck:
    conflicts = []
    compared = []
    for other in sorted(others, key=lambda i: str(i.id)):
        if other.id == current.id or not (result := classify(current, other)):
            continue
        kind, reason = result
        conflicts.append(
            CitationConflict(
                item_id=other.id,
                value=other.value,
                kind=kind,
                reason=reason,
                submitted=other.submitted,
            )
        )
        compared.append(
            (
                str(other.id),
                other.value,
                sorted(other.spans),
                sorted(other.aliases),
                other.identity,
                sorted(other.possible_aliases),
                other.incomplete,
                other.provenance_text,
                sorted(other.original_values),
            )
        )
    digest = hashlib.sha256(
        json.dumps(
            [
                str(current.id),
                current.value,
                sorted(current.spans),
                current.provenance_text,
                sorted(current.original_values),
                compared,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return CitationDuplicateCheck(fingerprint=digest, conflicts=conflicts)


def require_no_duplicates(check: CitationDuplicateCheck) -> None:
    confirmed = [c for c in check.conflicts if c.kind == "confirmed"]
    if confirmed:
        raise APIError(
            422,
            "citation_duplicate",
            "Duplicate item",
            "This citation already exists: "
            + "; ".join(
                f"{c.value} ({'submitted/read-only' if c.submitted else 'saved item'})"
                for c in confirmed
            ),
            errors=[
                FieldProblem(
                    path=["conflicts", str(c.item_id)], code="citation_duplicate", message=c.value
                )
                for c in confirmed
            ],
        )
