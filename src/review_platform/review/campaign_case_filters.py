"""Signed case-selection receipts and current-pool verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from review_platform.auth.service import now_utc
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.review.case_filter_identity import (
    CaseKey,
    PoolIdentitySet,
    _assert_identity_ready,
    _guarded_matches,
    find_pool_campaign,
    normalize_sources,
    pool_identities,
)
from review_platform.review.schemas.campaign_availability import (
    CampaignCaseFilter,
    CampaignCaseFilterApplyResponse,
    CampaignCaseIdApplyResponse,
    CampaignCaseIdSelection,
)

_RECEIPT_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class VerifiedCaseFilter:
    allowed_case_keys: frozenset[CaseKey] | None
    source_pool_cases_count: int
    case_filter_matching_count: int
    catalog_result_digest: str
    unidentifiable_pool_units_count: int = 0
    identity_unavailable_cases_count: int = 0
    identity_conflict_cases_count: int = 0


def _filter_digest(case_filter: CampaignCaseFilter) -> str:
    return digest_json(case_filter.model_dump(mode="json"))


def _case_id_selection_digest(case_id_selection: CampaignCaseIdSelection) -> str:
    return digest_json(case_id_selection.model_dump(mode="json"))


def _source_digest(source_families: list[str]) -> str:
    return digest_json(normalize_sources(source_families))


def _encode_receipt(payload: dict[str, Any], key: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(key.encode(), raw, hashlib.sha256).digest()
    return ".".join(
        base64.urlsafe_b64encode(part).rstrip(b"=").decode() for part in (raw, signature)
    )


def _decode_receipt(token: str, key: str) -> dict[str, Any]:
    try:
        raw_part, signature_part = token.split(".", 1)
        raw = base64.urlsafe_b64decode(raw_part + "=" * (-len(raw_part) % 4))
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(key.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise APIError(
            409,
            "applied_filter_invalid",
            "Apply filters again",
            "The applied case filter is invalid. Apply filters again.",
        ) from exc


def apply_case_filter(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
    database: DatasetCatalog,
    receipt_key: str,
) -> CampaignCaseFilterApplyResponse:
    verified = evaluate_case_filter(
        session,
        tenant_id=tenant_id,
        source_families=source_families,
        case_filter=case_filter,
        database=database,
    )
    issued = now_utc()
    expires = issued + _RECEIPT_TTL
    payload = {
        "v": 1,
        "kid": "campaign-filter-derived-v1",
        "tenant": str(tenant_id),
        "source": _source_digest(source_families),
        "filter": _filter_digest(case_filter),
        "result": verified.catalog_result_digest,
        "issued_at": int(issued.timestamp()),
        "expires_at": int(expires.timestamp()),
    }
    return CampaignCaseFilterApplyResponse(
        normalized_case_filter=case_filter,
        source_pool_cases_count=verified.source_pool_cases_count,
        case_filter_matching_count=verified.case_filter_matching_count,
        matching_count_by_source={
            "sample_a": sum(
                1
                for matching_source, _case_id in (verified.allowed_case_keys or frozenset())
                if matching_source == "sample_a"
            ),
            "sample_b": sum(
                1
                for matching_source, _case_id in (verified.allowed_case_keys or frozenset())
                if matching_source == "sample_b"
            ),
        },
        unidentifiable_pool_units_count=verified.unidentifiable_pool_units_count,
        identity_unavailable_cases_count=verified.identity_unavailable_cases_count,
        identity_conflict_cases_count=verified.identity_conflict_cases_count,
        catalog_result_digest=verified.catalog_result_digest,
        receipt_expires_at=expires,
        applied_filter_token=_encode_receipt(payload, receipt_key),
    )


def apply_case_id_selection(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_id_selection: CampaignCaseIdSelection,
    receipt_key: str,
) -> CampaignCaseIdApplyResponse:
    verified = evaluate_case_id_selection(
        session,
        tenant_id=tenant_id,
        source_families=source_families,
        case_id_selection=case_id_selection,
    )
    issued = now_utc()
    expires = issued + _RECEIPT_TTL
    payload = {
        "v": 1,
        "kid": "campaign-case-ids-derived-v1",
        "tenant": str(tenant_id),
        "source": _source_digest(source_families),
        "selection": _case_id_selection_digest(case_id_selection),
        "issued_at": int(issued.timestamp()),
        "expires_at": int(expires.timestamp()),
    }
    allowed = verified.allowed_case_keys or frozenset()
    matched_ids = {case_id for _source, case_id in allowed}
    return CampaignCaseIdApplyResponse(
        normalized_case_id_selection=case_id_selection,
        source_pool_cases_count=verified.source_pool_cases_count,
        uploaded_unique_count=len(case_id_selection.case_ids),
        case_id_matching_count=len(allowed),
        matching_count_by_source={
            "sample_a": sum(1 for source, _case_id in allowed if source == "sample_a"),
            "sample_b": sum(1 for source, _case_id in allowed if source == "sample_b"),
        },
        unmatched_case_ids=[
            case_id for case_id in case_id_selection.case_ids if case_id not in matched_ids
        ],
        receipt_expires_at=expires,
        applied_case_id_token=_encode_receipt(payload, receipt_key),
    )


def evaluate_case_id_selection(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_id_selection: CampaignCaseIdSelection,
) -> VerifiedCaseFilter:
    pool = find_pool_campaign(session, tenant_id=tenant_id)
    identities = (
        pool_identities(
            session,
            tenant_id=tenant_id,
            pool_campaign_id=pool.id,
            source_families=source_families,
        )
        if pool is not None
        else PoolIdentitySet(frozenset(), frozenset(), 0, 0, 0)
    )
    requested = set(case_id_selection.case_ids)
    allowed = frozenset(
        (source, case_id) for source, case_id in identities.logical if case_id in requested
    )
    return VerifiedCaseFilter(
        allowed_case_keys=allowed,
        source_pool_cases_count=len(identities.logical),
        case_filter_matching_count=len(allowed),
        catalog_result_digest=f"uploaded-case-ids:{digest_json(sorted(allowed))}",
        unidentifiable_pool_units_count=identities.unidentifiable_pool_units_count,
        identity_unavailable_cases_count=identities.identity_unavailable_cases_count,
        identity_conflict_cases_count=identities.identity_conflict_cases_count,
    )


def verify_case_id_selection(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_id_selection: CampaignCaseIdSelection,
    applied_case_id_token: str,
    receipt_key: str,
) -> VerifiedCaseFilter:
    payload = _decode_receipt(applied_case_id_token, receipt_key)
    if (
        payload.get("v") != 1
        or payload.get("kid") != "campaign-case-ids-derived-v1"
        or payload.get("tenant") != str(tenant_id)
        or payload.get("source") != _source_digest(source_families)
        or payload.get("selection") != _case_id_selection_digest(case_id_selection)
    ):
        raise APIError(
            409,
            "applied_case_id_mismatch",
            "Upload case IDs again",
            "The uploaded case IDs do not match this campaign request.",
        )
    if int(payload.get("expires_at", 0)) <= int(now_utc().timestamp()):
        raise APIError(
            409,
            "applied_case_id_expired",
            "Uploaded case IDs expired",
            "The uploaded case-ID selection expired — upload the file again.",
        )
    return evaluate_case_id_selection(
        session,
        tenant_id=tenant_id,
        source_families=source_families,
        case_id_selection=case_id_selection,
    )


def evaluate_case_filter(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
    database: DatasetCatalog,
) -> VerifiedCaseFilter:
    """Evaluate current pool intersection without issuing or accepting a browser receipt."""

    pool = find_pool_campaign(session, tenant_id=tenant_id)
    if pool is None:
        identities = PoolIdentitySet(frozenset(), frozenset(), 0, 0, 0)
    else:
        identities = pool_identities(
            session,
            tenant_id=tenant_id,
            pool_campaign_id=pool.id,
            source_families=source_families,
        )
    if case_filter.all:
        _assert_identity_ready(identities)
        catalog, result_digest = _guarded_matches(
            database,
            source_families=source_families,
            case_filter=case_filter,
        )
        matching = identities.guarded & catalog
        allowed = frozenset((source, case_id) for source, case_id, _sha in matching)
    else:
        result_digest = "no_catalog"
        allowed = None
    return VerifiedCaseFilter(
        allowed_case_keys=allowed,
        source_pool_cases_count=len(identities.logical),
        case_filter_matching_count=(
            len(allowed) if allowed is not None else len(identities.logical)
        ),
        catalog_result_digest=result_digest,
        unidentifiable_pool_units_count=identities.unidentifiable_pool_units_count,
        identity_unavailable_cases_count=identities.identity_unavailable_cases_count,
        identity_conflict_cases_count=identities.identity_conflict_cases_count,
    )


def verify_case_filter(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_families: list[str],
    case_filter: CampaignCaseFilter,
    applied_filter_token: str,
    database: DatasetCatalog,
    receipt_key: str,
) -> VerifiedCaseFilter:
    payload = _decode_receipt(applied_filter_token, receipt_key)
    if (
        payload.get("v") != 1
        or payload.get("kid") != "campaign-filter-derived-v1"
        or payload.get("tenant") != str(tenant_id)
        or payload.get("source") != _source_digest(source_families)
        or payload.get("filter") != _filter_digest(case_filter)
    ):
        raise APIError(
            409,
            "applied_filter_mismatch",
            "Apply filters again",
            "The applied filter does not match this campaign request.",
        )
    if int(payload.get("expires_at", 0)) <= int(now_utc().timestamp()):
        raise APIError(
            409,
            "applied_filter_expired",
            "Applied filter expired",
            "Applied filter expired — apply filters again.",
        )
    pool = find_pool_campaign(session, tenant_id=tenant_id)
    if pool is None:
        identities = PoolIdentitySet(frozenset(), frozenset(), 0, 0, 0)
    else:
        identities = pool_identities(
            session,
            tenant_id=tenant_id,
            pool_campaign_id=pool.id,
            source_families=source_families,
        )
    if case_filter.all:
        _assert_identity_ready(identities)
        catalog, digest = _guarded_matches(
            database,
            source_families=source_families,
            case_filter=case_filter,
        )
        if digest != payload.get("result"):
            raise APIError(
                409,
                "filter_snapshot_stale",
                "Filter results changed",
                "Dataset filter results changed. Apply filters again.",
            )
        matching = identities.guarded & catalog
        allowed = frozenset((source, case_id) for source, case_id, _sha in matching)
    else:
        digest = "no_catalog"
        allowed = None
    return VerifiedCaseFilter(
        allowed_case_keys=allowed,
        source_pool_cases_count=len(identities.logical),
        case_filter_matching_count=(
            len(allowed) if allowed is not None else len(identities.logical)
        ),
        catalog_result_digest=digest,
        unidentifiable_pool_units_count=identities.unidentifiable_pool_units_count,
        identity_unavailable_cases_count=identities.identity_unavailable_cases_count,
        identity_conflict_cases_count=identities.identity_conflict_cases_count,
    )
