from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import (
    Campaign,
)
from review_platform.review.schemas import (
    CampaignAvailabilityRequest,
    CampaignCaseFilter,
    CampaignCaseFilterApplyRequest,
    CampaignCaseIdApplyRequest,
    CampaignCaseIdSelection,
    CampaignEditRequest,
    CampaignReviewScopeInput,
    CreateCampaignRequest,
    LoadPoolCasesRequest,
)
from tests.support.identities import AdminIdentity
from tests.support.pool import (
    _SAMPLE_A_FIXTURE,
    _SAMPLE_B_FIXTURE,
    _case,
    _principal,
    _seed_pool,
    _service,
    _sha,
)


def test_source_filter_narrows_availability_to_the_selected_source(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha_sample_a = _sha(_SAMPLE_A_FIXTURE)
    sha_elit = _sha(_SAMPLE_B_FIXTURE)
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [
            _case("CAS-LN-1", sha_sample_a, source_system="sample_a"),
            _case("CAS-EL-1", sha_elit, source_system="sample_b"),
        ],
    )
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    sample_a_only = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(source_families=["sample_a"], requested_case_count="all"),
    )
    assert sample_a_only.eligible_cases_count == 1

    mixed = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count="all"),
    )
    assert mixed.eligible_cases_count == 2


def test_load_pool_cases_accepts_the_explicitly_applied_filter_state(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    draft = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(campaign_key="filtered-top-up", campaign_name="Filtered"),
        request_id="req-filter-shell",
    )
    applied = service.apply_campaign_case_filters(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignCaseFilterApplyRequest(),
    )

    topped_up = service.load_pool_cases(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=draft.campaign_id,
        body=LoadPoolCasesRequest(
            requested_case_count="all",
            case_filter=applied.normalized_case_filter,
            applied_filter_token=applied.applied_filter_token,
        ),
        request_id="req-filter-top-up",
    )

    assert topped_up.materialized_cases == 1
    assert topped_up.materialized_units == 1


def test_edit_published_campaign_persists_only_an_applied_case_filter(
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_platform.review import campaign_lifecycle

    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    draft = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(campaign_key="saved-filter", campaign_name="Saved filter"),
        request_id="req-filter-shell",
    )
    case_filter = CampaignCaseFilter.model_validate(
        {
            "all": [
                {
                    "field_id": "judgment_year",
                    "operator": "in_ranges",
                    "value": {"ranges": [{"start": 2016, "end": 2019}]},
                }
            ]
        }
    )

    with pytest.raises(APIError) as exc_info:
        service.edit_campaign(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=draft.campaign_id,
            body=CampaignEditRequest(case_filter=case_filter, confirm=True),
            request_id="req-filter-unapplied",
        )
    assert exc_info.value.code == "case_filter_not_applied"

    campaign = db_session.get(Campaign, draft.campaign_id)
    assert campaign is not None
    campaign.status = "published"
    db_session.flush()

    verified_sources: list[list[str]] = []
    monkeypatch.setattr(
        campaign_lifecycle,
        "verify_case_filter",
        lambda *_args, **kwargs: verified_sources.append(kwargs["source_families"]),
    )
    edited = service.edit_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=draft.campaign_id,
        body=CampaignEditRequest(
            review_scope=CampaignReviewScopeInput(source_families=["sample_b"]),
            case_filter=case_filter,
            applied_filter_token="applied-filter-receipt",
            confirm=True,
        ),
        request_id="req-filter-save",
    )

    assert verified_sources == [["sample_b"]]
    assert edited.case_filter == case_filter
    persisted = db_session.get(Campaign, draft.campaign_id)
    assert persisted is not None
    assert persisted.policy_json["case_filter"] == case_filter.model_dump(mode="json")
    assert "applied_filter_token" not in persisted.policy_json


def test_uploaded_case_ids_keep_constraining_adds_after_creation_and_edit(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [
            _case("CASE-1", _sha(), source_system="sample_a", groups=1),
            _case("CASE-3", _sha(), source_system="sample_a", groups=1),
            _case("CASE-4", _sha(), source_system="sample_a", groups=1),
            _case("CASE-5", _sha(), source_system="sample_a", groups=1),
            _case("CASE-6", _sha(), source_system="sample_a", groups=1),
            _case(
                "CASE-2",
                _sha(_SAMPLE_B_FIXTURE),
                source_system="sample_b",
                groups=1,
            ),
        ],
    )
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    selection = CampaignCaseIdSelection(case_ids=["CASE-1", "CASE-2", "CASE-3", "MISSING"])
    applied = service.apply_campaign_case_ids(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignCaseIdApplyRequest(source_families=["sample_a"], case_id_selection=selection),
    )

    assert applied.case_id_matching_count == 2
    assert applied.unmatched_case_ids == ["CASE-2", "MISSING"]
    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="uploaded-case-ids",
            campaign_name="Uploaded case IDs",
            review_scope=CampaignReviewScopeInput(source_families=["sample_a"]),
            requested_case_count=1,
            case_id_selection=selection,
            applied_case_id_token=applied.applied_case_id_token,
            case_id_selection_file_name="initial-case-ids.txt",
        ),
        request_id="req-upload-create",
    )
    assert created.availability is not None
    assert created.availability.eligible_cases_count == 2
    persisted_after_create = db_session.get(Campaign, created.campaign_id)
    assert persisted_after_create is not None
    # Existing campaigns can have the old flag set to false and still have a saved selection.
    persisted_after_create.policy_json = {
        **persisted_after_create.policy_json,
        "case_selection_applies_to_topups": False,
    }
    db_session.flush()

    detail = service.get_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=created.campaign_id,
    )
    assert detail.case_id_selection == selection
    assert detail.case_id_selection_file_name == "initial-case-ids.txt"

    def add_cases(count: int | Literal["all"]) -> int:
        return service.load_pool_cases(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=created.campaign_id,
            body=LoadPoolCasesRequest(requested_case_count=count),
            request_id="req-upload-top-up",
        ).materialized_cases

    assert add_cases("all") == 1

    reapplied = service.apply_campaign_case_ids(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignCaseIdApplyRequest(source_families=["sample_a"], case_id_selection=selection),
    )
    assert reapplied.case_id_matching_count == 0
    assert reapplied.unmatched_case_ids == ["CASE-1", "CASE-2", "CASE-3", "MISSING"]

    replacement = CampaignCaseIdSelection(case_ids=["CASE-4", "CASE-5"])
    replacement_applied = service.apply_campaign_case_ids(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignCaseIdApplyRequest(
            source_families=["sample_a"], case_id_selection=replacement
        ),
    )
    persisted_after_create.status = "published"
    db_session.flush()
    edited = service.edit_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=created.campaign_id,
        body=CampaignEditRequest(
            case_id_selection=replacement,
            applied_case_id_token=replacement_applied.applied_case_id_token,
            case_id_selection_file_name="replacement-case-ids.txt",
            confirm=True,
        ),
        request_id="req-upload-edit",
    )
    assert edited.case_id_selection == replacement

    assert add_cases(1) == 1
    assert add_cases("all") == 1
    with pytest.raises(APIError) as exhausted:
        add_cases("all")
    assert exhausted.value.code == "campaign_no_cases_available"
    detail_after_top_up = service.get_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=created.campaign_id,
    )
    assert detail_after_top_up.case_id_selection == replacement
    assert detail_after_top_up.case_id_selection_file_name == "replacement-case-ids.txt"
    campaign_cases = service.campaign_cases(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=created.campaign_id,
        limit=10,
        cursor=None,
    )
    assert {row.case_id for row in campaign_cases.items} == {
        "CASE-1",
        "CASE-3",
        "CASE-4",
        "CASE-5",
    }
