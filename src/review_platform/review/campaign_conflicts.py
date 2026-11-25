"""Both importers (``real_import``, ``synthetic_import``) tag every persisted ``ReviewSubject``
with a ``snapshot_local_case_external_id`` attribute -- the reviewed case's own external id,
distinct from ``snapshot_local_target_external_id`` which, for a relation unit, identifies
the relation's *target* (e.g. the cited case), not the case being reviewed. This module
reads that attribute, never the target one, to group units by the case actually under
review."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.grouping import classify_unit
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit

# Every non-terminal campaign status. There is no distinct "archived" status (see the lifecycle
# contract doc); a closed campaign's units are deliberately excluded from the guard.
_ACTIVE_STATUSES = ("draft", "planned", "published", "paused")


@dataclass(frozen=True)
class CaseFieldCandidate:
    case_id: str
    review_kind: str
    safe_field_label: str


@dataclass(frozen=True)
class CaseFieldConflict:
    case_id: str
    group_id: str
    group_label: str
    campaign_id: uuid.UUID
    campaign_key: str


def find_case_field_conflicts(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    exclude_campaign_id: uuid.UUID | None,
    candidates: Iterable[CaseFieldCandidate],
) -> list[CaseFieldConflict]:
    """Return every ``candidates`` entry already assigned to a different active campaign.

    ``exclude_campaign_id`` is the campaign the candidates would be written into -- its own prior
    units, if any, are never a conflict with themselves (idempotent re-import).
    """

    candidate_groups: dict[tuple[str, str], str] = {}
    for candidate in candidates:
        group = classify_unit(candidate.review_kind, candidate.safe_field_label)
        candidate_groups[(candidate.case_id, group.group_id)] = group.group_label
    if not candidate_groups:
        return []
    case_ids = {case_id for case_id, _group_id in candidate_groups}

    case_id_column = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    stmt = (
        select(
            case_id_column,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            Campaign.id,
            Campaign.key,
        )
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .join(
            Campaign,
            (Campaign.tenant_id == ReviewUnit.tenant_id) & (Campaign.id == ReviewUnit.campaign_id),
        )
        .where(
            ReviewUnit.tenant_id == tenant_id,
            Campaign.status.in_(_ACTIVE_STATUSES),
            case_id_column.in_(case_ids),
        )
    )
    if exclude_campaign_id is not None:
        stmt = stmt.where(Campaign.id != exclude_campaign_id)

    conflicts: dict[tuple[str, str], CaseFieldConflict] = {}
    for case_id, review_kind, safe_field_label, campaign_id, campaign_key in session.execute(stmt):
        if case_id is None:
            continue
        group = classify_unit(review_kind, safe_field_label)
        key = (case_id, group.group_id)
        if key in candidate_groups and key not in conflicts:
            conflicts[key] = CaseFieldConflict(
                case_id=case_id,
                group_id=group.group_id,
                group_label=candidate_groups[key],
                campaign_id=campaign_id,
                campaign_key=campaign_key,
            )
    return list(conflicts.values())


def conflict_detail_payload(conflicts: Iterable[CaseFieldConflict]) -> list[dict[str, str]]:
    """Machine-readable conflict list for an API/CLI error response."""

    return [
        {
            "case_id": conflict.case_id,
            "group_id": conflict.group_id,
            "group_label": conflict.group_label,
            "campaign_id": str(conflict.campaign_id),
            "campaign_key": conflict.campaign_key,
        }
        for conflict in conflicts
    ]
