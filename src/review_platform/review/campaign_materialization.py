"""Transactional pool claims and campaign field-scope expansion."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from review_platform.review.availability_queries import (
    _campaign_units,
    _CampaignUnitRow,
    _claimed_groups_for_cases,
)
from review_platform.review.campaign_availability import CaseCountRequest
from review_platform.review.campaign_missing_values import _synthesize_missing_unit
from review_platform.review.grouping import classify_unit
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit

# PostgreSQL allows 65,535 bound parameters; leave room for the tenant and campaign
# parameters as well as the UUID list in each movement update.
_MOVEMENT_BATCH_SIZE = 50_000


def materialize_from_pool(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign: Campaign,
    target_campaign: Campaign,
    source_families: list[str],
    group_ids: list[str],
    case_count: CaseCountRequest,
    required_reviews: int,
    allow_partial_fields: bool = False,
    synthesize_missing: bool = False,
    allowed_case_keys: frozenset[tuple[str, str]] | None = None,
    pool_rows: list[_CampaignUnitRow] | None = None,
) -> tuple[int, int]:
    """Reassign eligible pool review units into ``target_campaign``; return (cases, units)
    moved.

    With a declared field scope and ``synthesize_missing=False`` (the default --
    byte-for-byte the pre-existing behaviour), only cases with *every* requested field
    group present in the pool are selected (a case with only some requested fields left
    stays in the pool -- selecting it here would silently create a campaign that can
    never satisfy its own declared field scope for that case). With an empty scope the
    campaign declares no groups, so every pooled case is eligible and all of its units
    move. Mirrors ``compute_availability``; keep the two in step. Selection order is
    stable (case id, then unit id) so repeated calls with a growing ``case_count`` are
    deterministic top-ups, matching ``DatasetImportService``'s own idempotent-top-up
    semantics.

    ``synthesize_missing=True`` (the campaign-creation opt-in flag,
    ``CreateCampaignRequest.synthesize_missing_values``) selects every pooled case
    regardless of group coverage and, for each requested group a selected case doesn't
    already have a pool unit for, inserts a new ``missing``-state ``ReviewUnit``
    directly into ``target_campaign`` (see ``_synthesize_missing_unit``) instead of
    reassigning an existing row. The existing reassignment path below is unchanged for
    groups the case already has extracted.

    Claim serialization relies on ``lock_pool_claims``'s tenant-scoped transaction advisory
    lock, which callers acquire before both availability computation and this update. We
    deliberately do not ``FOR UPDATE`` every row in the tenant pool: at production scale
    that would take up to a million row locks even though the advisory lock already
    excludes competing campaign claims. The update still predicates on ``campaign_id ==
    pool_campaign.id`` as a fail-closed guard.

    ``allow_partial_fields`` is the admin's explicit ``confirm_remaining_fields_only``
    decision: the all-or-nothing rule is relaxed so a case that carries *any* requested
    field is selected, moving just the requested fields it has. The caller must have
    already narrowed ``group_ids`` to the non-exhausted requested groups so the campaign
    never declares a field no case can supply. Not used together with
    ``synthesize_missing`` (which makes the all-or-nothing rule moot)."""

    rows = (
        pool_rows
        if pool_rows is not None
        else _campaign_units(session, tenant_id=tenant_id, campaign_id=pool_campaign.id)
    )
    if source_families:
        rows = [row for row in rows if row.source_system in source_families]
    if allowed_case_keys is not None:
        rows = [row for row in rows if row.case_key in allowed_case_keys]
    scoped = bool(group_ids)
    requested_set = set(group_ids)

    by_case: dict[tuple[str, str], list[_CampaignUnitRow]] = defaultdict(list)
    all_case_ids: set[tuple[str, str]] = set()
    for row in rows:
        if row.case_key is None:
            continue
        all_case_ids.add(row.case_key)
        if not scoped or row.group_id in requested_set:
            by_case[row.case_key].append(row)

    claimed_by_case = (
        _claimed_groups_for_cases(
            session,
            tenant_id=tenant_id,
            pool_campaign_id=pool_campaign.id,
            case_keys=all_case_ids,
            target_campaign_id=target_campaign.id,
        )
        if scoped
        else {}
    )
    if claimed_by_case:
        by_case = {
            case_key: [
                row for row in case_rows if row.group_id not in claimed_by_case.get(case_key, set())
            ]
            for case_key, case_rows in by_case.items()
        }

    if synthesize_missing and scoped:
        # Selecting a field group never reduces eligibility: every pooled case is a candidate, and
        # a case's missing requested groups become synthesized units below.
        eligible_case_ids = sorted(
            case_key
            for case_key in all_case_ids
            if not (claimed_by_case.get(case_key, set()) & requested_set)
        )
    else:
        eligible_case_ids = sorted(
            case_id
            for case_id, case_rows in by_case.items()
            if not scoped
            or allow_partial_fields
            or {r.group_id for r in case_rows} >= requested_set
        )
    cap = None if case_count == "all" else case_count
    selected_case_ids = eligible_case_ids if cap is None else eligible_case_ids[:cap]

    selected_unit_ids = [
        row.review_unit_id for case_key in selected_case_ids for row in by_case.get(case_key, [])
    ]
    synthesized_units = 0
    if synthesize_missing and scoped:
        for source_system, case_id in selected_case_ids:
            covered_groups = {row.group_id for row in by_case.get((source_system, case_id), [])}
            for group_id in sorted(requested_set - covered_groups):
                _synthesize_missing_unit(
                    session,
                    tenant_id=tenant_id,
                    pool_campaign=pool_campaign,
                    target_campaign=target_campaign,
                    case_id=case_id,
                    source_system=source_system,
                    group_id=group_id,
                    required_reviews=required_reviews,
                )
                synthesized_units += 1
    if not selected_unit_ids and not synthesized_units:
        return 0, 0
    if not selected_unit_ids:
        return len(selected_case_ids), synthesized_units
    moved_units = _move_selected_units(
        session,
        tenant_id=tenant_id,
        pool_campaign_id=pool_campaign.id,
        target_campaign_id=target_campaign.id,
        required_reviews=required_reviews,
        selected_unit_ids=selected_unit_ids,
    )
    return len(selected_case_ids), moved_units + synthesized_units


def _move_selected_units(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign_id: uuid.UUID,
    target_campaign_id: uuid.UUID,
    required_reviews: int,
    selected_unit_ids: Sequence[uuid.UUID],
) -> int:
    """Move one exact preselected UUID set in parameter-safe batches inside the caller's txn."""

    if len(selected_unit_ids) != len(set(selected_unit_ids)):
        raise RuntimeError("campaign materialization selected duplicate review-unit UUIDs")
    moved_units = 0
    for start in range(0, len(selected_unit_ids), _MOVEMENT_BATCH_SIZE):
        batch_unit_ids = selected_unit_ids[start : start + _MOVEMENT_BATCH_SIZE]
        result = cast(
            CursorResult[Any],
            session.execute(
                update(ReviewUnit)
                .where(
                    ReviewUnit.tenant_id == tenant_id,
                    ReviewUnit.campaign_id == pool_campaign_id,
                    ReviewUnit.id.in_(batch_unit_ids),
                )
                .values(
                    campaign_id=target_campaign_id,
                    required_reviews=required_reviews,
                    lock_version=ReviewUnit.lock_version + 1,
                )
            ),
        )
        moved_units += result.rowcount
    if moved_units != len(selected_unit_ids):
        raise RuntimeError(
            "campaign materialization moved a different number of units than selected"
        )
    return moved_units


@dataclass(frozen=True)
class ScopeWidenConflict:
    """One case/group the campaign cannot take on because another campaign already holds it."""

    case_id: str
    group_id: str
    campaign_key: str


def backfill_widened_scope(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign: Campaign,
    target_campaign: Campaign,
    added_group_ids: list[str],
    required_reviews: int,
) -> tuple[int, list[ScopeWidenConflict]]:
    """Pull the campaign's *existing* cases' units for newly-scoped groups out of the pool.

    Widening a campaign's field scope used to update ``review_scope_json`` and nothing else,
    so the cases already in the campaign kept only their original fields while cases
    loaded afterwards got the wider set -- one campaign, two different per-case field
    coverages. This closes that gap: the newly added groups are materialized for the
    cases the campaign already holds.

    Field scope stays **disjoint across campaigns**. A case/group pair that some other
    non-pool campaign already owns is returned as a conflict and *nothing* is moved; the
    caller rejects the edit rather than widening coverage it cannot honour. Units
    already in ``target_campaign`` are not conflicts (re-adding a group the campaign
    already has is a no-op), and units still in the pool are exactly what gets moved.

    Returns ``(units_moved, conflicts)``. When ``conflicts`` is non-empty ``units_moved`` is
    0 and no rows were written."""

    if not added_group_ids:
        return 0, []
    added = set(added_group_ids)
    case_ids = {
        row.case_id
        for row in _campaign_units(session, tenant_id=tenant_id, campaign_id=target_campaign.id)
    }
    if not case_ids:
        return 0, []

    # A case/group pair is one conflict however many units make it up -- a case with 40 cited-case
    # rows must not report the same clash 40 times in the operator's error message.
    conflicting: set[ScopeWidenConflict] = set()
    movable_unit_ids: list[uuid.UUID] = []
    for unit_id, case_id, group_id, campaign_id, campaign_key in _units_for_cases(
        session, tenant_id=tenant_id, case_ids=case_ids
    ):
        if group_id not in added or case_id not in case_ids:
            continue
        if campaign_id == target_campaign.id:
            continue
        if campaign_id == pool_campaign.id:
            movable_unit_ids.append(unit_id)
        else:
            conflicting.add(ScopeWidenConflict(case_id, group_id, campaign_key))
    if conflicting:
        # Deterministic order so the API message and its tests are stable.
        return 0, sorted(conflicting, key=lambda c: (c.case_id, c.group_id, c.campaign_key))
    if not movable_unit_ids:
        return 0, []
    session.execute(
        update(ReviewUnit)
        .where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == pool_campaign.id,
            ReviewUnit.id.in_(movable_unit_ids),
        )
        .values(
            campaign_id=target_campaign.id,
            required_reviews=required_reviews,
            lock_version=ReviewUnit.lock_version + 1,
        )
    )
    return len(movable_unit_ids), []


def _units_for_cases(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    case_ids: set[str],
) -> list[tuple[uuid.UUID, str, str, uuid.UUID, str]]:
    """Every unit belonging to ``case_ids``, tagged with the campaign that currently holds it."""

    case_id_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    stmt = (
        select(
            ReviewUnit.id,
            case_id_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
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
        .where(ReviewUnit.tenant_id == tenant_id, case_id_col.in_(case_ids))
    )
    rows = []
    for (
        unit_id,
        case_id,
        review_kind,
        safe_field_label,
        field_name,
        campaign_id,
        campaign_key,
    ) in session.execute(stmt):
        if case_id is None:  # pragma: no cover - every imported row carries this attribute
            continue
        group = classify_unit(review_kind, safe_field_label, field_name)
        rows.append((unit_id, case_id, group.group_id, campaign_id, campaign_key))
    return rows
