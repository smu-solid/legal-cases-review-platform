from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.review import campaign_availability
from review_platform.review.availability_queries import _CampaignUnitStat
from review_platform.review.campaign_availability import compute_availability
from review_platform.review.campaign_case_filters import (
    VerifiedCaseFilter,
    apply_case_filter,
    apply_case_id_selection,
    verify_case_filter,
    verify_case_id_selection,
)
from review_platform.review.case_filter_export import case_filter_export
from review_platform.review.case_filter_identity import PoolIdentitySet, _catalog_rows
from review_platform.review.schemas.campaign_availability import (
    CampaignCaseFilter,
    CampaignCaseIdSelection,
)

pytestmark = pytest.mark.no_db


def test_empty_filter_receipt_is_pool_only_and_verifiable() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    tenant_id = uuid.uuid4()
    case_filter = CampaignCaseFilter()

    applied = apply_case_filter(
        session,
        tenant_id=tenant_id,
        source_families=[],
        case_filter=case_filter,
        database=DatasetCatalog(None),
        receipt_key="r" * 64,
    )
    verified = verify_case_filter(
        session,
        tenant_id=tenant_id,
        source_families=[],
        case_filter=case_filter,
        applied_filter_token=applied.applied_filter_token,
        database=DatasetCatalog(None),
        receipt_key="r" * 64,
    )

    assert applied.catalog_result_digest == "no_catalog"
    assert applied.case_filter_matching_count == 0
    assert verified.allowed_case_keys is None


def test_receipt_is_bound_to_source_scope() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    tenant_id = uuid.uuid4()
    case_filter = CampaignCaseFilter()
    applied = apply_case_filter(
        session,
        tenant_id=tenant_id,
        source_families=["sample_a"],
        case_filter=case_filter,
        database=DatasetCatalog(None),
        receipt_key="r" * 64,
    )

    with pytest.raises(APIError, match="does not match") as exc_info:
        verify_case_filter(
            session,
            tenant_id=tenant_id,
            source_families=["sample_b"],
            case_filter=case_filter,
            applied_filter_token=applied.applied_filter_token,
            database=DatasetCatalog(None),
            receipt_key="r" * 64,
        )
    assert exc_info.value.code == "applied_filter_mismatch"


def test_uploaded_case_ids_are_normalized_matched_and_return_unmatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    pool = MagicMock()
    pool.id = uuid.uuid4()
    session.scalar.return_value = pool
    monkeypatch.setattr(
        "review_platform.review.campaign_case_filters.pool_identities",
        lambda *_args, **_kwargs: PoolIdentitySet(
            guarded=frozenset(),
            logical=frozenset({("sample_a", "CASE-1"), ("sample_a", "CASE-2")}),
            unidentifiable_pool_units_count=0,
            identity_unavailable_cases_count=0,
            identity_conflict_cases_count=0,
        ),
    )
    selection = CampaignCaseIdSelection(
        case_ids=["\ufeffCASE-1 ", "CASE-1", " MISSING ", "", "CASE-2"]
    )

    applied = apply_case_id_selection(
        session,
        tenant_id=uuid.uuid4(),
        source_families=["sample_a"],
        case_id_selection=selection,
        receipt_key="r" * 64,
    )

    assert selection.case_ids == ["CASE-1", "MISSING", "CASE-2"]
    assert applied.case_id_matching_count == 2
    assert applied.unmatched_case_ids == ["MISSING"]
    assert applied.matching_count_by_source == {"sample_a": 2, "sample_b": 0}


def test_uploaded_case_id_receipt_is_bound_to_source(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    tenant_id = uuid.uuid4()
    selection = CampaignCaseIdSelection(case_ids=["CASE-1"])
    applied = apply_case_id_selection(
        session,
        tenant_id=tenant_id,
        source_families=["sample_a"],
        case_id_selection=selection,
        receipt_key="r" * 64,
    )

    with pytest.raises(APIError, match="do not match") as exc_info:
        verify_case_id_selection(
            session,
            tenant_id=tenant_id,
            source_families=["sample_b"],
            case_id_selection=selection,
            applied_case_id_token=applied.applied_case_id_token,
            receipt_key="r" * 64,
        )
    assert exc_info.value.code == "applied_case_id_mismatch"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "version": "v1",
            "all": [{"field_id": "case_subject", "operator": "eq", "value": "Criminal"}],
        },
        {
            "version": "v1",
            "all": [{"field_id": "judgment_year", "operator": "eq", "value": 999}],
        },
        {
            "version": "v1",
            "all": [
                {"field_id": "case_subject", "operator": "contains_ci", "value": "one"},
                {"field_id": "case_subject", "operator": "contains_ci", "value": "two"},
            ],
        },
    ],
)
def test_closed_filter_contract_rejects_invalid_clauses(payload: object) -> None:
    with pytest.raises(ValidationError):
        CampaignCaseFilter.model_validate(payload)


def test_synthesis_excludes_a_case_when_requested_group_is_owned_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_key = ("sample_a", "case-1")
    monkeypatch.setattr(
        campaign_availability,
        "_campaign_unit_stats",
        lambda *_args, **_kwargs: [_CampaignUnitStat("case-1", "available_group", "sample_a", 1)],
    )
    monkeypatch.setattr(
        campaign_availability,
        "_claimed_groups_for_cases",
        lambda *_args, **_kwargs: {case_key: {"claimed_group"}},
    )

    result = compute_availability(
        MagicMock(spec=Session),
        tenant_id=uuid.uuid4(),
        pool_campaign_id=uuid.uuid4(),
        source_families=["sample_a"],
        group_ids=["available_group", "claimed_group"],
        requested_case_count="all",
        synthesize_missing=True,
    )

    assert result.eligible_cases_count == 0
    assert result.overlap_cases_count == 1
    assert result.overlap_group_counts == (("claimed_group", 1),)


def test_disjoint_claimed_group_does_not_block_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_key = ("sample_a", "case-1")
    monkeypatch.setattr(
        campaign_availability,
        "_campaign_unit_stats",
        lambda *_args, **_kwargs: [_CampaignUnitStat("case-1", "requested_group", "sample_a", 1)],
    )
    monkeypatch.setattr(
        campaign_availability,
        "_claimed_groups_for_cases",
        lambda *_args, **_kwargs: {case_key: {"different_group"}},
    )

    result = compute_availability(
        MagicMock(spec=Session),
        tenant_id=uuid.uuid4(),
        pool_campaign_id=uuid.uuid4(),
        source_families=["sample_a"],
        group_ids=["requested_group"],
        requested_case_count="all",
        synthesize_missing=True,
    )

    assert result.eligible_cases_count == 1
    assert result.overlap_cases_count == 0


@pytest.mark.parametrize(
    "start,end",
    [(999, 1000), (9999, 10000), (2019, 2018)],
)
def test_judgment_year_ranges_reject_invalid_bounds(start: int, end: int) -> None:
    with pytest.raises(ValidationError):
        CampaignCaseFilter.model_validate(
            {
                "all": [
                    {
                        "field_id": "judgment_year",
                        "operator": "in_ranges",
                        "value": {"ranges": [{"start": start, "end": end}]},
                    }
                ]
            }
        )


def test_case_export_combines_and_deduplicates_ids_with_a_safe_filter_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_filter = CampaignCaseFilter.model_validate(
        {
            "all": [
                {"field_id": "case_subject", "operator": "contains_ci", "value": "Criminal"},
                {
                    "field_id": "judgment_year",
                    "operator": "in_ranges",
                    "value": {
                        "ranges": [
                            {"start": 2010, "end": 2010},
                            {"start": 2014, "end": 2014},
                            {"start": 2016, "end": 2019},
                        ]
                    },
                },
            ]
        }
    )
    monkeypatch.setattr(
        "review_platform.review.case_filter_export.verify_case_filter",
        lambda *_args, **_kwargs: VerifiedCaseFilter(
            allowed_case_keys=frozenset(
                {
                    ("sample_b", "CAS-2"),
                    ("sample_b", "CAS-1"),
                    ("sample_a", "CAS-1"),
                    ("sample_a", "CAS-3"),
                }
            ),
            source_pool_cases_count=3,
            case_filter_matching_count=3,
            catalog_result_digest="digest",
        ),
    )

    exported = case_filter_export(
        MagicMock(spec=Session),
        tenant_id=uuid.uuid4(),
        source_families=[],
        case_filter=case_filter,
        applied_filter_token="token",
        database=DatasetCatalog(None),
        receipt_key="r" * 64,
    )

    assert exported.filename == "case_ids_criminal_2010_2014_2016to2019.txt"
    assert exported.content == "CAS-1\nCAS-2\nCAS-3\n"


def test_catalogue_filter_treats_query_as_literal_and_checks_years():
    class Catalogue:
        def cases(self):
            return [
                {
                    "source_system": "sample_a",
                    "external_id": "A",
                    "sha256": "a" * 64,
                    "subject": "Contract ' OR 1=1 --",
                    "judgment_date": "2024-01-01",
                },
                {
                    "source_system": "sample_b",
                    "external_id": "B",
                    "sha256": "b" * 64,
                    "subject": "Property",
                    "judgment_date": "2020-01-01",
                },
            ]

    clause = CampaignCaseFilter.model_validate(
        {
            "all": [
                {"field_id": "case_subject", "operator": "contains_ci", "value": "' OR 1=1 --"},
                {"field_id": "judgment_year", "operator": "eq", "value": 2024},
            ]
        }
    )
    matches = _catalog_rows(Catalogue(), source_families=[], case_filter=clause)
    assert [row["external_id"] for row in matches] == ["A"]
    assert _catalog_rows(Catalogue(), source_families=["sample_b"], case_filter=clause) == []
