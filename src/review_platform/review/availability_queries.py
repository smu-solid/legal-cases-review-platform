"""Classified pool snapshots, aggregate counts, and existing campaign ownership."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.review.grouping import classify_unit
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit


@dataclass(frozen=True)
class _CampaignUnitRow:
    review_unit_id: uuid.UUID
    case_id: str
    group_id: str
    source_system: str | None
    source_sha256: str | None

    @property
    def case_key(self) -> tuple[str, str] | None:
        if self.source_system is None:
            return None
        return (self.source_system, self.case_id)


@dataclass(frozen=True)
class _CampaignUnitStat:
    """Per-(case, group) unit count -- all ``compute_availability`` needs from the pool."""

    case_id: str
    group_id: str
    source_system: str | None
    unit_count: int

    @property
    def case_key(self) -> tuple[str, str] | None:
        if self.source_system is None:
            return None
        return (self.source_system, self.case_id)


@dataclass(frozen=True)
class CampaignOverlapSummary:
    campaign_id: uuid.UUID
    campaign_key: str
    campaign_name: str
    cases_count: int
    group_counts: tuple[tuple[str, int], ...]


def _campaign_units(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> list[_CampaignUnitRow]:
    """Classified units currently held by one campaign (usually the pool)."""

    case_id_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    sha_col = ReviewSubject.attributes_json["source_sha256"].astext
    stmt = (
        select(
            ReviewUnit.id,
            case_id_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
            source_col,
            sha_col,
        )
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign_id)
    )
    rows = []
    for (
        unit_id,
        case_id,
        review_kind,
        safe_field_label,
        field_name,
        source_system,
        source_sha256,
    ) in session.execute(stmt):
        if case_id is None:  # pragma: no cover - every pool row carries this attribute by import
            continue
        group = classify_unit(review_kind, safe_field_label, field_name)
        rows.append(
            _CampaignUnitRow(unit_id, case_id, group.group_id, source_system, source_sha256)
        )
    return rows


def load_campaign_units(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[_CampaignUnitRow]:
    """Load a reusable unit snapshot for one serialized availability/materialization decision."""

    return _campaign_units(session, tenant_id=tenant_id, campaign_id=campaign_id)


def _campaign_unit_stats(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> list[_CampaignUnitStat]:
    """Per-(case, group) unit counts for one campaign, aggregated in the database.

    The GROUP BY runs over the ``classify_unit`` inputs (kind, label, field name) because the
    group mapping is Python-side; classified duplicates of one (case, group) are merged below.
    Compared to ``_campaign_units`` this returns no unit ids and no sha256, and collapses
    multi-unit relation groups, so a full-pool availability preview stops scaling its memory
    with unit count.
    """

    case_id_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    stmt = (
        select(
            case_id_col,
            source_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
            func.count().label("unit_count"),
        )
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign_id)
        .group_by(
            case_id_col,
            source_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
        )
    )
    merged: Counter[tuple[str, str | None, str]] = Counter()
    for (
        case_id,
        source_system,
        review_kind,
        safe_field_label,
        field_name,
        unit_count,
    ) in session.execute(stmt):
        if case_id is None:  # pragma: no cover - every pool row carries this attribute by import
            continue
        group = classify_unit(review_kind, safe_field_label, field_name)
        merged[(case_id, source_system, group.group_id)] += unit_count
    return [
        _CampaignUnitStat(case_id, group_id, source_system, count)
        for (case_id, source_system, group_id), count in merged.items()
    ]


def _stats_from_rows(rows: list[_CampaignUnitRow]) -> list[_CampaignUnitStat]:
    """Aggregate an already-loaded unit snapshot (the serialized claim path) into stats."""

    merged: Counter[tuple[str, str | None, str]] = Counter()
    for row in rows:
        merged[(row.case_id, row.source_system, row.group_id)] += 1
    return [
        _CampaignUnitStat(case_id, group_id, source_system, count)
        for (case_id, source_system, group_id), count in merged.items()
    ]


def _claimed_groups_for_cases(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign_id: uuid.UUID,
    case_keys: set[tuple[str, str]],
    target_campaign_id: uuid.UUID | None,
) -> dict[tuple[str, str], set[str]]:
    """Requested-case groups currently held outside the pool and optional target campaign."""

    if not case_keys:
        return {}
    # Claimed units are, by definition, the ones held OUTSIDE the pool (and the optional target
    # campaign), so exclude those campaigns in SQL and fetch only the small claimed remainder.
    # The previous shape did the opposite -- an IN-list of every requested case id with the
    # campaign exclusion applied in Python -- which on a full-pool preview (19,798 cases) pulled
    # every unit in the tenant back out of the database a second time per request.
    excluded_campaigns = [
        campaign_id for campaign_id in (pool_campaign_id, target_campaign_id) if campaign_id
    ]
    case_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    stmt = (
        select(
            case_col,
            source_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
        )
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id.not_in(excluded_campaigns))
    )
    claimed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for case_id, source, review_kind, safe_label, field_name in session.execute(stmt):
        case_key = (source, case_id)
        if source is None or case_key not in case_keys:
            continue
        claimed[case_key].add(classify_unit(review_kind, safe_label, field_name).group_id)
    return claimed


def _claimed_campaign_overlaps_for_cases(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign_id: uuid.UUID,
    case_keys: set[tuple[str, str]],
    target_campaign_id: uuid.UUID | None,
    requested_groups: set[str] | None,
) -> tuple[CampaignOverlapSummary, ...]:
    """Summarize omitted case/group ownership by the campaigns that currently hold it."""

    if not case_keys:
        return ()
    # Same inversion as _claimed_groups_for_cases: exclude the pool/target campaigns in SQL and
    # fetch only the small claimed remainder instead of an every-case IN-list filtered in Python.
    excluded_campaigns = [
        campaign_id for campaign_id in (pool_campaign_id, target_campaign_id) if campaign_id
    ]
    case_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    stmt = (
        select(
            case_col,
            source_col,
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
            Campaign.id,
            Campaign.key,
            Campaign.name,
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
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id.not_in(excluded_campaigns))
    )
    campaign_cases: dict[uuid.UUID, set[tuple[str, str]]] = defaultdict(set)
    campaign_groups: dict[uuid.UUID, dict[str, set[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    campaign_labels: dict[uuid.UUID, tuple[str, str]] = {}
    for (
        case_id,
        source,
        review_kind,
        safe_label,
        field_name,
        campaign_id,
        campaign_key,
        campaign_name,
    ) in session.execute(stmt):
        case_key = (source, case_id)
        if source is None or case_key not in case_keys:
            continue
        group_id = classify_unit(review_kind, safe_label, field_name).group_id
        if requested_groups is not None and group_id not in requested_groups:
            continue
        campaign_labels[campaign_id] = (campaign_key, campaign_name)
        campaign_cases[campaign_id].add(case_key)
        campaign_groups[campaign_id][group_id].add(case_key)
    return tuple(
        CampaignOverlapSummary(
            campaign_id=campaign_id,
            campaign_key=campaign_labels[campaign_id][0],
            campaign_name=campaign_labels[campaign_id][1],
            cases_count=len(campaign_cases[campaign_id]),
            group_counts=tuple(
                sorted(
                    (group_id, len(cases))
                    for group_id, cases in campaign_groups[campaign_id].items()
                )
            ),
        )
        for campaign_id in sorted(campaign_labels, key=lambda item: campaign_labels[item][0])
    )
