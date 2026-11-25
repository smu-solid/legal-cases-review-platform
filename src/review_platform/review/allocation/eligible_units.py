"""Typed lightweight rows shared by allocation planning and drift validation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


def allocation_case_key(
    *, case_id: object, external_subject_id: str, review_subject_id: uuid.UUID
) -> str:
    """Return the stable case key, preserving the legacy subject fallback."""

    if isinstance(case_id, str) and case_id:
        return case_id
    return f"subject:{external_subject_id or review_subject_id}"


@dataclass(frozen=True, slots=True)
class EligibleUnit:
    """The complete allocation-facing projection of one eligible review unit."""

    review_unit_id: uuid.UUID
    review_subject_id: uuid.UUID
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    subject_kind: str
    review_kind: str
    safe_field_label: str
    field_name: str | None
    snapshot_local_case_external_id: object
    external_subject_id: str
    citation_metrics: Any
    display_title: str

    @property
    def case_key(self) -> str:
        return allocation_case_key(
            case_id=self.snapshot_local_case_external_id,
            external_subject_id=self.external_subject_id,
            review_subject_id=self.review_subject_id,
        )


CaseUnits = dict[str, list[EligibleUnit]]
