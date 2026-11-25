"""Case filter identity."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.review.case_pool import POOL_CAMPAIGN_KEY
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit
from review_platform.review.schemas.campaign_availability import (
    CampaignCaseFilter,
    CampaignJudgmentYearValue,
)

CaseKey = tuple[str, str]


GuardedCaseKey = tuple[str, str, str]


_ALLOWED_SOURCES = frozenset({"sample_a", "sample_b"})


@dataclass(frozen=True)
class PoolIdentitySet:
    guarded: frozenset[GuardedCaseKey]
    logical: frozenset[CaseKey]
    unidentifiable_pool_units_count: int
    identity_unavailable_cases_count: int
    identity_conflict_cases_count: int


def normalize_sources(source_families: list[str]) -> list[str]:
    sources = sorted(set(source_families))
    if any(source not in _ALLOWED_SOURCES for source in sources):
        raise APIError(422, "campaign_source_invalid", "Invalid source", "Unknown source family.")
    return sources


def find_pool_campaign(session: Session, *, tenant_id: uuid.UUID) -> Campaign | None:
    """Resolve the pool without creating it; Apply/preview/corrections are read-like."""

    return session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id,
            Campaign.key == POOL_CAMPAIGN_KEY,
        )
    )


def pool_identities(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign_id: uuid.UUID,
    source_families: list[str],
) -> PoolIdentitySet:
    sources = normalize_sources(source_families)
    case_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    sha_col = ReviewSubject.attributes_json["source_sha256"].astext
    rows = session.execute(
        select(case_col, source_col, sha_col)
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == pool_campaign_id,
        )
    )

    unidentifiable = 0
    sha_by_key: dict[CaseKey, set[str]] = defaultdict(set)
    missing_sha_keys: set[CaseKey] = set()
    logical: set[CaseKey] = set()
    for case_id, source, source_sha in rows:
        if not case_id or not source:
            unidentifiable += 1
            continue
        if sources and source not in sources:
            continue
        key = (source, case_id)
        logical.add(key)
        if source_sha:
            sha_by_key[key].add(source_sha)
        else:
            missing_sha_keys.add(key)

    unavailable = sum(1 for key in logical if not sha_by_key[key] or key in missing_sha_keys)
    conflicts = sum(1 for key in logical if len(sha_by_key[key]) > 1)
    guarded = {
        (source, case_id, next(iter(sha_by_key[(source, case_id)])))
        for source, case_id in logical
        if len(sha_by_key[(source, case_id)]) == 1 and (source, case_id) not in missing_sha_keys
    }
    return PoolIdentitySet(
        guarded=frozenset(guarded),
        logical=frozenset(logical),
        unidentifiable_pool_units_count=unidentifiable,
        identity_unavailable_cases_count=unavailable,
        identity_conflict_cases_count=conflicts,
    )


def _catalog_rows(
    database: DatasetCatalog,
    *,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
    include_subject: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sources = normalize_sources(source_families)
    rows = []
    for row in database.cases():
        if sources and row["source_system"] not in sources:
            continue
        matches = True
        for clause in case_filter.all:
            if clause.field_id == "case_subject":
                matches = (
                    matches
                    and str(clause.value).casefold() in (row.get("subject") or "").casefold()
                )
            else:
                if not isinstance(clause.value, CampaignJudgmentYearValue):
                    raise ValueError("invalid year filter")
                ranges = clause.value.ranges
                year = int(row["judgment_date"][:4]) if row.get("judgment_date") else None
                matches = (
                    matches and year is not None and any(v.start <= year <= v.end for v in ranges)
                )
        if matches:
            rows.append(row)
    return rows[:limit] if limit is not None else rows


def _guarded_matches(
    database: DatasetCatalog,
    *,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
) -> tuple[frozenset[GuardedCaseKey], str]:
    rows = _catalog_rows(
        database,
        source_families=source_families,
        case_filter=case_filter,
    )
    identities = frozenset(
        (str(row["source_system"]), str(row["external_id"]), str(row["sha256"])) for row in rows
    )
    return identities, digest_json(sorted(identities))


def _assert_identity_ready(identities: PoolIdentitySet) -> None:
    if (
        identities.unidentifiable_pool_units_count
        or identities.identity_unavailable_cases_count
        or identities.identity_conflict_cases_count
    ):
        raise APIError(
            409,
            "pool_identity_not_ready",
            "Pool identity not ready",
            "Some pool cases do not have a complete, agreeing source identity. Remediate the "
            "pool before applying a non-empty case filter.",
            diagnostics={
                "unidentifiable_pool_units_count": identities.unidentifiable_pool_units_count,
                "identity_unavailable_cases_count": identities.identity_unavailable_cases_count,
                "identity_conflict_cases_count": identities.identity_conflict_cases_count,
            },
        )
