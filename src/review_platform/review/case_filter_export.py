"""Case-ID downloads and subject correction suggestions."""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.review.campaign_case_filters import verify_case_filter
from review_platform.review.case_filter_identity import (
    _assert_identity_ready,
    _catalog_rows,
    find_pool_campaign,
    pool_identities,
)
from review_platform.review.schemas.campaign_availability import (
    CampaignCaseFilter,
    CampaignCaseFilterSuggestion,
)


@dataclass(frozen=True)
class CaseFilterExport:
    filename: str
    content: str


_FILENAME_PART_RE = re.compile(r"[^a-z0-9]+")


def _filename_part(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _FILENAME_PART_RE.sub("_", ascii_value.casefold()).strip("_")[:80] or "filter"


def case_filter_export(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
    applied_filter_token: str | None,
    database: DatasetCatalog,
    receipt_key: str,
) -> CaseFilterExport:
    """Export unique case IDs from the current pool or an applied filter."""

    if case_filter.all:
        if not applied_filter_token:
            raise APIError(
                422,
                "case_filter_export_requires_filter",
                "Apply filters first",
                "Apply the case filters before exporting.",
            )
        verified = verify_case_filter(
            session,
            tenant_id=tenant_id,
            source_families=source_families,
            case_filter=case_filter,
            applied_filter_token=applied_filter_token,
            database=database,
            receipt_key=receipt_key,
        )
        case_keys = verified.allowed_case_keys or frozenset()
    else:
        pool = find_pool_campaign(session, tenant_id=tenant_id)
        case_keys = (
            pool_identities(
                session,
                tenant_id=tenant_id,
                pool_campaign_id=pool.id,
                source_families=source_families,
            ).logical
            if pool is not None
            else frozenset()
        )

    case_ids = sorted({case_id for _, case_id in case_keys})
    if not case_ids:
        raise APIError(
            409,
            "case_filter_export_empty",
            "No matching cases",
            "There are no matching cases to export.",
        )

    filename_parts = ["case_ids"]
    for clause in case_filter.all:
        if clause.field_id == "case_subject":
            filename_parts.append(_filename_part(str(clause.value)))
        else:
            year_parts = [
                str(item.start) if item.start == item.end else f"{item.start}to{item.end}"
                for item in clause.value.ranges  # type: ignore[union-attr]
            ]
            filename_parts.extend(year_parts)
    return CaseFilterExport(
        filename="_".join(filename_parts) + ".txt",
        content="".join(f"{case_id}\n" for case_id in case_ids),
    )


_SEPARATOR_RE = re.compile(r"[\n\r\[\](){};\-\u2010-\u2015]+")


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _typo_normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}


def suggest_case_subjects(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    query: str,
    limit: int,
    database: DatasetCatalog,
) -> list[CampaignCaseFilterSuggestion]:
    pool = find_pool_campaign(session, tenant_id=tenant_id)
    if pool is None:
        return []
    identities = pool_identities(
        session,
        tenant_id=tenant_id,
        pool_campaign_id=pool.id,
        source_families=source_families,
    )
    _assert_identity_ready(identities)
    rows = _catalog_rows(
        database,
        source_families=source_families,
        case_filter=CampaignCaseFilter(),
        include_subject=True,
        limit=10_000,
    )
    pool_rows = [
        row
        for row in rows
        if (str(row["source_system"]), str(row["external_id"]), str(row["sha256"]))
        in identities.guarded
        and row.get("subject")
    ]
    candidates: dict[str, str] = {}
    for row in pool_rows:
        subject = unicodedata.normalize("NFKC", str(row["subject"]))
        forms = _SEPARATOR_RE.split(subject)[:20]
        forms.extend(_TOKEN_RE.findall(subject))
        for form in forms[:64]:
            display = form.strip(" \t.,:!?\"'")[:80]
            normalized = _typo_normalize(display)
            if display and 4 <= len(normalized) <= 80:
                candidates.setdefault(normalized, display)
            if len(candidates) >= 20_000:
                break
        if len(candidates) >= 20_000:
            break
    normalized_query = _typo_normalize(query)
    query_bigrams = _bigrams(normalized_query)
    minimum = max(4, math.floor(0.60 * len(normalized_query)))
    maximum = math.ceil(1.67 * len(normalized_query))
    shortlist: list[tuple[float, int, str, str]] = []
    for normalized, display in candidates.items():
        if not minimum <= len(normalized) <= maximum or normalized == normalized_query:
            continue
        candidate_bigrams = _bigrams(normalized)
        union = query_bigrams | candidate_bigrams
        overlap = len(query_bigrams & candidate_bigrams) / len(union) if union else 0.0
        if (len(normalized_query) < 5 and not query_bigrams & candidate_bigrams) or (
            len(normalized_query) >= 5 and overlap < 0.25
        ):
            continue
        shortlist.append(
            (-overlap, abs(len(normalized) - len(normalized_query)), normalized, display)
        )
    scored = []
    for _overlap, _distance, normalized, display in sorted(shortlist)[:500]:
        score = SequenceMatcher(None, normalized_query, normalized).ratio()
        if score >= 0.82:
            matching_keys = {
                (str(row["source_system"]), str(row["external_id"]))
                for row in pool_rows
                if display.lower() in str(row["subject"]).lower()
            }
            scored.append((score, len(matching_keys), normalized, display))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [
        CampaignCaseFilterSuggestion(
            value=display,
            confidence=round(score, 4),
            matching_pool_cases_count=count,
        )
        for score, count, _normalized, display in scored[:limit]
    ]
