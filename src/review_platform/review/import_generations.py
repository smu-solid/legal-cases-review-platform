"""Logical identity lookup, locking, and replacement of unassigned import generations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from review_platform.review.import_source import (
    DatasetImportError,
    DatasetImportResult,
    _CaseSource,
)
from review_platform.review.models import (
    Assignment,
    Campaign,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.review.subject_attributes import subject_attribute as _subject_attr

if TYPE_CHECKING:
    from review_platform.review.dataset_import import DatasetImportService


def _matched_unit_keys(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    external_item_key: str,
    legacy_item_keys: list[str] | None,
) -> list[str]:
    probe_keys = [external_item_key, *(key[:240] for key in (legacy_item_keys or []))]
    matched_keys: list[str] = []
    for probe in probe_keys:
        hit = session.scalar(
            select(SourceSnapshot.id).where(
                SourceSnapshot.tenant_id == tenant_id,
                SourceSnapshot.external_item_key == probe,
            )
        )
        if hit is None:
            hit = session.scalar(
                select(ReviewSubject.id)
                .where(
                    ReviewSubject.tenant_id == tenant_id,
                    _subject_attr("logical_external_item_key") == probe,
                )
                .limit(1)
            )
        if hit is not None:
            matched_keys.append(probe)
    return matched_keys


def _lock_refresh_generation(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    matched_keys: list[str],
    external_item_key: str,
) -> tuple[ReviewUnit, list[uuid.UUID], set[uuid.UUID]]:
    candidate_snapshot_ids: set[uuid.UUID] = set()
    primary_snapshot_ids: set[uuid.UUID] = set()
    for key in matched_keys:
        key_ids = set(
            session.scalars(
                select(SourceSnapshot.id).where(
                    SourceSnapshot.tenant_id == tenant_id,
                    SourceSnapshot.external_item_key == key,
                )
            )
        ) | set(
            session.scalars(
                select(ReviewSubject.source_snapshot_id).where(
                    ReviewSubject.tenant_id == tenant_id,
                    _subject_attr("logical_external_item_key") == key,
                )
            )
        )
        candidate_snapshot_ids |= key_ids
        if key == external_item_key:
            primary_snapshot_ids = key_ids
    current_unit = (
        session.scalar(
            select(ReviewUnit)
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .join(
                SourceSnapshot,
                (SourceSnapshot.tenant_id == ReviewSubject.tenant_id)
                & (SourceSnapshot.id == ReviewSubject.source_snapshot_id),
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign.id,
                # The CURRENT generation is the primary-key one whenever it exists: a
                # newer legacy sibling must never outrank the family-keyed generation and
                # masquerade as "the unit" whose digest decides changed/unchanged.
                SourceSnapshot.id.in_(primary_snapshot_ids or candidate_snapshot_ids),
            )
            .order_by(SourceSnapshot.imported_at.desc())
            .limit(1)
            .with_for_update()
        )
        if candidate_snapshot_ids
        else None
    )
    if current_unit is None:
        raise DatasetImportError(
            f"refusing to refresh {external_item_key}: item is not currently in the case pool"
        )
    # Destructive adoption is scoped to THIS campaign's generations only: matching
    # units in other campaigns are never retired here (the cross-campaign conflict guard
    # owns that boundary). Rows are locked so a concurrent allocation cannot acquire a
    # candidate between the assignment check and its retirement.
    candidate_unit_ids = list(
        session.scalars(
            select(ReviewUnit.id)
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign.id,
                ReviewSubject.source_snapshot_id.in_(candidate_snapshot_ids),
            )
            .with_for_update()
        )
    )
    has_assignment = session.scalar(
        select(Assignment.id).where(
            Assignment.tenant_id == tenant_id,
            Assignment.review_unit_id.in_(candidate_unit_ids),
        )
    )
    if has_assignment is not None:
        raise DatasetImportError(
            f"refusing to refresh {external_item_key}: pool item has an assignment"
        )
    return current_unit, candidate_unit_ids, primary_snapshot_ids


def _delete_superseded_generation(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    unit_id: uuid.UUID,
    plain_key: str | None = None,
) -> None:
    """Delete a retired pool generation outright, leaving no displaced copy behind.

    Deletes the ``SourceSnapshot`` the unit hangs off; ``review_subjects``, ``review_units``,
    ``candidates``, ``evidence_windows`` and ``source_render_artifacts`` all cascade from it.
    Callers must have established that the unit holds no assignment.

    ``plain_key`` additionally clears an orphaned snapshot still occupying the unsuffixed
    ``external_item_key`` -- the residue of the superseded ARCHIVE scheme this replaced, whose
    units carried ``:refresh:<uuid>`` keys. Without this the replacement insert would collide
    on ``uq_snapshot_external_item`` for any item refreshed under the old scheme.
    """

    snapshot_id = session.scalar(
        select(ReviewSubject.source_snapshot_id)
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
            & (ReviewUnit.review_subject_id == ReviewSubject.id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.id == unit_id)
    )
    doomed = [snapshot_id] if snapshot_id is not None else []
    if plain_key is not None:
        stale = session.scalar(
            select(SourceSnapshot.id).where(
                SourceSnapshot.tenant_id == tenant_id,
                SourceSnapshot.external_item_key == plain_key,
            )
        )
        if stale is not None and stale != snapshot_id:
            doomed.append(stale)
    if not doomed:
        return
    session.execute(
        delete(SourceSnapshot).where(
            SourceSnapshot.tenant_id == tenant_id,
            SourceSnapshot.id.in_(doomed),
        )
    )
    session.flush()


def _reconcile_unchanged(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    current_unit: ReviewUnit,
    candidate_unit_ids: list[uuid.UUID],
    matched_keys: list[str],
    external_item_key: str,
    result: DatasetImportResult,
) -> None:
    current_snapshot_id = session.scalar(
        select(ReviewSubject.source_snapshot_id).where(
            ReviewSubject.tenant_id == tenant_id,
            ReviewSubject.id == current_unit.review_subject_id,
        )
    )
    sibling_ids = [uid for uid in candidate_unit_ids if uid != current_unit.id]
    for unit_id in sibling_ids:
        self._delete_superseded_generation(session, tenant_id=tenant_id, unit_id=unit_id)
    # Orphan snapshots still occupying a legacy key (no unit) are cleared too — but
    # NEVER the kept generation's own snapshot.
    for key in matched_keys:
        if key == external_item_key:
            continue
        stale = session.scalar(
            select(SourceSnapshot.id).where(
                SourceSnapshot.tenant_id == tenant_id,
                SourceSnapshot.external_item_key == key,
            )
        )
        if stale is not None and stale != current_snapshot_id:
            session.execute(
                delete(SourceSnapshot).where(
                    SourceSnapshot.tenant_id == tenant_id,
                    SourceSnapshot.id == stale,
                )
            )
        result.reconciled_legacy_keys.append({"old_key": key, "new_key": external_item_key})
    session.flush()


def _prepare_generation(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    external_item_key: str,
    legacy_item_keys: list[str] | None,
    input_digest: str,
    refresh_existing: bool,
    source: _CaseSource,
    result: DatasetImportResult,
) -> bool:
    matched_keys = _matched_unit_keys(
        session,
        tenant_id=tenant_id,
        external_item_key=external_item_key,
        legacy_item_keys=legacy_item_keys,
    )
    existing = matched_keys[0] if matched_keys else None
    if existing is not None:
        if not refresh_existing:
            return False  # ordinary provisioning remains idempotent
        # Same shape split as the presence probes above, for the same reason: the OR across
        # the join is un-indexable and re-scanned every pooled row per refreshed unit. The
        # matching generations are resolved first through the two indexed probes, then the
        # newest one holding a unit in THIS campaign is selected and locked exactly as
        # before (order, limit and FOR UPDATE unchanged; a handful of ids at most).
        current_unit, candidate_unit_ids, primary_snapshot_ids = _lock_refresh_generation(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            matched_keys=matched_keys,
            external_item_key=external_item_key,
        )
        if primary_snapshot_ids and current_unit.input_digest == input_digest:
            # The family-keyed root generation is genuinely unchanged and is KEPT — nothing of
            # it is deleted or rewritten. Any OTHER matched generation is a legacy-keyed
            # duplicate of the same logical unit and is still reconciled here: an unchanged
            # root must never leave a stale sibling assignable (independent review N3).
            _reconcile_unchanged(
                self,
                session,
                tenant_id=tenant_id,
                current_unit=current_unit,
                candidate_unit_ids=candidate_unit_ids,
                matched_keys=matched_keys,
                external_item_key=external_item_key,
                result=result,
            )
            return False  # unchanged root generation kept; siblings reconciled

        # Hard replacement: the superseded generation is DELETED, not moved aside. Deleting
        # the snapshot cascades subject -> unit -> candidates/evidence_windows, so one
        # statement retires the whole generation and frees the plain external_item_key for
        # the replacement below. The assignment guard above means a unit a reviewer holds is
        # never in scope here.
        # Force the source BEFORE the first mutation. Everything above decided only whether to
        # write; from here on rows are deleted and added, and a source that has become
        # unreadable must fail this case cleanly rather than half-replace a unit. The values
        # are bound after the branch, where they are used; this call is a guard.
        source.require()
        # Retire EVERY matched generation of this logical unit — the newest (locked) one and
        # any sibling legacy-keyed generations — then clear each matched plain key. One
        # replacement unit follows; a legacy sibling surviving here would remain a second
        # assignable copy of the same family field.
        for unit_id in candidate_unit_ids:
            self._delete_superseded_generation(session, tenant_id=tenant_id, unit_id=unit_id)
        for key in matched_keys:
            self._delete_superseded_generation(
                session, tenant_id=tenant_id, unit_id=current_unit.id, plain_key=key
            )
        for key in matched_keys:
            if key != external_item_key:
                # Legacy member-keyed generations were ADOPTED by the family key: replaced in
                # place (unassigned by the guard above) and manifested for the operator.
                result.reconciled_legacy_keys.append({"old_key": key, "new_key": external_item_key})
    return True
