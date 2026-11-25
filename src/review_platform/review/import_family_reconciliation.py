"""Protect canonical families and retire only unassigned pool copies."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from review_platform.dataset.types import InputCase
from review_platform.review.grouping import scope_matches
from review_platform.review.import_source import DatasetImportError, _CaseSource, _field_label
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


def _legacy_member_ids(case: InputCase) -> list[str]:
    """Member observation ids other than the family key itself (the legacy unit-key owners)."""
    family = case.family_id or case.external_id
    return [m for m in (case.member_external_ids or ()) if m and m != family]


def _incoming_logical_keys(
    self: DatasetImportService, case: InputCase, campaign: Campaign
) -> set[str]:
    """Logical keys this import may write in THIS campaign's scope, for the family key AND
    every legacy member identity (disjoint scopes elsewhere never collide)."""

    members = [case.family_id or case.external_id, *self._legacy_member_ids(case)]
    keys: set[str] = set()
    for field in case.fields:
        if scope_matches(
            "metadata_field",
            _field_label(field.field_name),
            campaign.review_scope_json,
            source_system=case.source_system,
            field_name=field.field_name,
        ):
            keys.update(f"{member}:{field.field_name}" for member in members)
    for relation in case.relations:
        if scope_matches(
            relation.review_kind,
            relation.display_label,
            campaign.review_scope_json,
            source_system=case.source_system,
        ):
            relation_ids = {entry["relation_external_id"] for entry in relation.contributing} | {
                relation.relation_external_id
            }
            keys.update(
                f"{member}:{relation.family}:{relation_id}"
                for member in members
                for relation_id in relation_ids
            )
    return keys


def _family_protected_legacy_units(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    case: InputCase,
    campaign: Campaign | None = None,
) -> list[str]:
    """Unit keys carrying protected work that this family import cannot safely re-key.

    Three protected shapes defer the WHOLE family (independent review N4):

    1. member-keyed units with an assignment — the reviewer's assignment/submission/audit
       trail hangs off the raw member identity;
    2. family-keyed units with an assignment whose PERSISTED membership differs from the
       incoming membership — a membership transition on held work is ambiguous and is
       deferred with evidence, never resolved by rewriting submissions;
    3. units of ANOTHER family whose persisted membership overlaps an incoming member — the
       member moved between grouped families while the OLD family holds protected work
       (historical membership; current member lists alone cannot identify it).

    A family-keyed assigned unit whose membership is UNCHANGED is not a blocker: an unchanged
    digest passes through untouched, and a changed one still hits the per-unit refusal.
    """
    family = case.family_id or case.external_id
    incoming = sorted(case.member_external_ids or (case.external_id,))
    family_prefix = f"{family}:"
    incoming_keys = self._incoming_logical_keys(case, campaign) if campaign else set()
    protected = (
        select(
            _subject_attr("logical_external_item_key"),
            _subject_attr("snapshot_local_case_external_id"),
            _subject_attr("family_id"),
            ReviewSubject.attributes_json["family_member_external_ids"],
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
        )
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
            & (ReviewUnit.review_subject_id == ReviewSubject.id),
        )
        .join(
            Assignment,
            (Assignment.tenant_id == ReviewUnit.tenant_id)
            & (Assignment.review_unit_id == ReviewUnit.id),
        )
        .where(ReviewSubject.tenant_id == tenant_id)
    )
    blockers: set[str] = set()
    incoming_set = set(incoming)
    for key, raw_case_id, stored_family, stored_members, kind, label, field in session.execute(
        protected
    ):
        stored_member_list = sorted(str(m) for m in (stored_members or []) if m)
        overlap = bool(set(stored_member_list) & incoming_set) or raw_case_id in incoming_set
        if not overlap:
            continue
        if key and not key.startswith(family_prefix):
            blockers.add(key)  # member-keyed or other-family protected work
        elif key and stored_member_list and stored_member_list != incoming:
            blockers.add(key)  # family-keyed held work with a membership transition
        elif stored_family and stored_family != family:
            blockers.add(key or f"{stored_family}:<unit>")
        elif not stored_family:
            # A PRE-GROUPING row (no persisted family) whose raw identity is this family's
            # ROOT carries a root-prefixed key indistinguishable from the family key. Its
            # assignment/submission trail is protected work all the same: defer.
            blockers.add(key or f"{raw_case_id}:<legacy-unit>")
        elif (
            campaign
            and key not in incoming_keys
            and scope_matches(
                kind,
                label,
                campaign.review_scope_json,
                source_system=case.source_system,
                field_name=field,
            )
        ):
            # An excluded ordinary item may have no successor key at all. Its saved work
            # still holds this family, even if every retained item is currently unassigned.
            blockers.add(key or f"{raw_case_id}:<removed-unit>")
    # 4. a unit of this family's identities living in ANOTHER (non-pool) campaign under a key
    #    this import is about to (re)write holds the family: the refresh would otherwise find
    #    the key outside the pool and abort the whole run ("not currently in the case pool").
    #    Disjoint scopes in other campaigns (different keys) are legitimate and not blocked.
    if campaign is not None:
        held_elsewhere = session.execute(
            select(
                _subject_attr("logical_external_item_key"),
                Campaign.key,
                ReviewUnit.review_kind,
                ReviewUnit.safe_field_label,
                ReviewUnit.field_name,
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
                & (ReviewUnit.review_subject_id == ReviewSubject.id),
            )
            .join(
                Campaign,
                (Campaign.tenant_id == ReviewUnit.tenant_id)
                & (Campaign.id == ReviewUnit.campaign_id),
            )
            .where(
                ReviewSubject.tenant_id == tenant_id,
                Campaign.id != campaign.id,
                Campaign.status != "pool",
                or_(
                    _subject_attr("logical_external_item_key").in_(sorted(incoming_keys)),
                    _subject_attr("snapshot_local_case_external_id").in_([family, *incoming]),
                ),
            )
        ).all()
        for key, campaign_key, kind, label, field in held_elsewhere:
            if key in incoming_keys or scope_matches(
                kind,
                label,
                campaign.review_scope_json,
                source_system=case.source_system,
                field_name=field,
            ):
                blockers.add(f"{key}@{campaign_key}")
    return sorted(blockers)


def _retire_unassigned_pool_copies(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    case: InputCase,
) -> list[str]:
    """Delete this POOL campaign's UNASSIGNED units for every identity of a deferred family.

    Assigned pool units (if any) are left untouched; returned ids are recorded in the family's
    reconciliation manifest entry. Never touches another campaign.
    """

    if campaign.status != "pool":
        return []
    members = [case.family_id or case.external_id, *self._legacy_member_ids(case)]
    unit_ids = list(
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
                _subject_attr("snapshot_local_case_external_id").in_(members),
            )
            .with_for_update()
        )
    )
    if not unit_ids:
        return []
    assigned = set(
        session.scalars(
            select(Assignment.review_unit_id).where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id.in_(unit_ids),
            )
        )
    )
    retired: list[str] = []
    for unit_id in unit_ids:
        if unit_id in assigned:
            continue
        self._delete_superseded_generation(session, tenant_id=tenant_id, unit_id=unit_id)
        retired.append(str(unit_id))
    return retired


def _delete_removed_pool_units(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    case: InputCase,
    source: _CaseSource,
) -> None:
    """The removal scan covers EVERY member identity of the family (a legacy member-keyed unit is
    this family's unit under its previous identity), and the incoming-key set includes each
    unit's legacy equivalents, so a unit about to be ADOPTED by its family key is never
    mistaken for a removed input."""

    if campaign.status != "pool":
        raise DatasetImportError("refusing to refresh inputs outside the case pool")
    members = [case.family_id or case.external_id, *self._legacy_member_ids(case)]
    incoming_keys = self._incoming_logical_keys(case, campaign)
    rows = session.execute(
        select(ReviewUnit, ReviewSubject, SourceSnapshot)
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
            _subject_attr("snapshot_local_case_external_id").in_(members),
        )
        .with_for_update(of=ReviewUnit)
    ).all()
    retired_ids = []
    for unit, subject, snapshot in rows:
        # Missing-value tasks are synthesized by allocation, not extracted source rows.
        if unit.extraction_state == "missing" or not scope_matches(
            unit.review_kind,
            unit.safe_field_label,
            campaign.review_scope_json,
            source_system=case.source_system,
            field_name=unit.field_name,
        ):
            continue
        logical_key = (
            subject.attributes_json.get("logical_external_item_key")
            or snapshot.external_item_key.split(":refresh:", 1)[0]
        )
        if logical_key not in incoming_keys:
            retired_ids.append(unit.id)
    if not retired_ids:
        return
    has_assignment = session.scalar(
        select(Assignment.id).where(
            Assignment.tenant_id == tenant_id,
            Assignment.review_unit_id.in_(retired_ids),
        )
    )
    if has_assignment is not None:
        raise DatasetImportError(
            f"refusing to refresh {case.external_id}: a removed pool input has an assignment"
        )
    source.require()  # No cleanup if the selected document vanished after resolution.
    for unit_id in retired_ids:
        self._delete_superseded_generation(session, tenant_id=tenant_id, unit_id=unit_id)
