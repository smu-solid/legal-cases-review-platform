from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.db.session import Database
from review_platform.review.allocation.schemas import (
    SubjectPoolPreviewRequest,
)
from review_platform.review.allocation.service import AllocationService
from review_platform.review.models import (
    Campaign,
    ReviewUnit,
    SourceRenderArtifact,
)
from review_platform.review.schemas import (
    CampaignAvailabilityRequest,
    CampaignReviewScopeInput,
    CreateCampaignRequest,
    LoadPoolCasesRequest,
)
from review_platform.settings import Settings
from tests.support.identities import AdminIdentity
from tests.support.pool import (
    _case,
    _ensure_admin_is_reviewer,
    _principal,
    _seed_pool,
    _service,
    _sha,
)


def test_availability_preview_reports_no_cases_for_an_empty_pool(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(requested_case_count=30),
    )
    assert result.feasibility == "infeasible_no_cases"
    assert result.eligible_cases_count == 0


def test_availability_preview_warns_in_backend_logs_when_pool_looks_unseeded(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """An empty pool logs a diagnostic hint pointing at the tenant-mismatch runbook/tool."""

    logger = logging.getLogger("review_platform")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    previous_disabled = logger.disabled
    previous_level = logger.level
    logger.disabled = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        service = _service(tmp_path)
        result = service.preview_campaign_availability(
            db_session,
            tenant_id=admin.tenant_id,
            principal=_principal(db_session, admin),
            body=CampaignAvailabilityRequest(requested_case_count=30),
        )
    finally:
        logger.removeHandler(handler)
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)

    assert result.feasibility == "infeasible_no_cases"
    assert any("pool_looks_unseeded" in record.getMessage() for record in records)


def test_availability_is_scoped_to_the_seeded_tenant_not_a_sibling_tenant(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A pool preloaded for one tenant must not be visible from another tenant's admin view."""
    from review_platform.db.models import Tenant

    imported = _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", _sha())])
    assert imported == 2  # citation_neutral + coram fields, both landing on the one seeded case

    other_tenant = Tenant(key="tenant-sibling-unseeded", name="Sibling (unseeded)")
    db_session.add(other_tenant)
    db_session.flush()

    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    seeded_result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count="all"),
    )
    assert seeded_result.eligible_cases_count == 1

    unseeded_result = service.preview_campaign_availability(
        db_session,
        tenant_id=other_tenant.id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count="all"),
    )
    assert unseeded_result.eligible_cases_count == 0
    assert unseeded_result.feasibility == "infeasible_no_cases"


def test_create_campaign_requesting_more_than_available_requires_confirmation(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    response = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="pilot-30", campaign_name="Pilot 30", requested_case_count=30
        ),
        request_id="req-1",
    )
    assert response.availability is not None
    assert response.availability.feasibility == "feasible_with_smaller_count"
    assert response.availability.eligible_cases_count == 2
    assert response.not_ready_for_publish is True
    assert response.total_units == 0  # nothing materialized without confirmation

    confirmed = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="pilot-30-confirmed",
            campaign_name="Pilot 30 confirmed",
            requested_case_count=30,
            confirm_smaller_count=True,
        ),
        request_id="req-2",
    )
    assert confirmed.not_ready_for_publish is False
    assert confirmed.total_units == 4  # 2 cases * 2 fields each


def test_create_campaign_exact_count_available_is_feasible_without_confirmation(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha)])
    service = _service(tmp_path)
    response = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CreateCampaignRequest(
            campaign_key="pilot-2", campaign_name="Pilot 2", requested_case_count=2
        ),
        request_id="req-1",
    )
    assert response.availability is not None
    assert response.availability.feasibility == "feasible_exact"
    assert response.not_ready_for_publish is False
    assert response.total_units == 4


def test_fields_partially_available_when_only_some_cases_have_the_requested_group(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    # CAS-1 has only the case_metadata field -- court_and_hearing never appears for it, but it does
    # exist elsewhere in the pool (CAS-2), so the field is exhausted for CAS-1 specifically without
    # being exhausted for the whole source (feasible_with_remaining_fields_only, not infeasible).
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1), _case("CAS-2", sha)])
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count=2
        ),
    )
    assert result.fields_fully_exhausted == []
    assert result.fields_partially_available == ["court_and_hearing"]
    assert result.feasibility == "feasible_with_smaller_count"  # only CAS-2 has both fields


def test_fields_fully_exhausted_when_no_case_anywhere_has_the_requested_group(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    # Every pool case here has only the case_metadata field -- court_and_hearing never appears.
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count=1
        ),
    )
    assert result.fields_fully_exhausted == ["court_and_hearing"]
    # case_metadata is still available (CAS-1 has it), so this is a partial match, not a wipeout.
    assert result.feasibility == "feasible_with_remaining_fields_only"


def test_remaining_fields_only_when_no_case_has_every_selected_field(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    # CAS-1 has both groups, CAS-2 only case_metadata -- but CAS-1's court_and_hearing unit is
    # already claimed by another (active) campaign, so only a partial match remains for anyone else.
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="claims-court",
            campaign_name="Claims court field",
            review_scope=None,
            requested_case_count=1,
            confirm_remaining_fields_only=True,
        ),
        request_id="req-claim",
    )
    # After the claim above (CAS-1, both groups moved out since review_scope was unrestricted),
    # only CAS-2's case_metadata unit remains in the pool -- so a case_metadata+court_and_hearing
    # request now finds no case with *both* groups, only some cases with a subset.
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count=1
        ),
    )
    assert result.eligible_cases_count == 0
    # CAS-1 (both fields) was claimed entirely; CAS-2 (case_metadata only) is still in the pool, so
    # it is a partial match for this two-field request, not an empty pool.
    assert result.cases_available_for_some_selected_fields_only == 1


def test_confirm_remaining_fields_only_materializes_the_partial_cases(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Regression: confirming remaining-fields-only must materialize the partial cases, not
    silently     produce an empty draft. The draft's declared scope is narrowed to the
    fields that can appear."""

    sha = _sha()
    # Claim CAS-1 (both groups) with an unrestricted campaign, leaving only CAS-2 (case_metadata
    # only) in the pool -- so a case_metadata+court_and_hearing request matches no case with both.
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="claim-both", campaign_name="Claim both", requested_case_count=1
        ),
        request_id="req-claim-both",
    )

    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="remaining-only",
            campaign_name="Remaining only",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata", "court_and_hearing"]),
            requested_case_count=1,
            confirm_remaining_fields_only=True,
        ),
        request_id="req-remaining",
    )
    assert created.availability is not None
    assert created.availability.feasibility == "feasible_with_remaining_fields_only"
    assert created.not_ready_for_publish is False
    # CAS-2's single case_metadata unit is materialized -- not an empty draft.
    assert created.total_units == 1
    # The draft's scope narrows to the field that can appear (court_and_hearing dropped).
    campaign = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id, Campaign.key == "remaining-only"
        )
    )
    assert campaign is not None
    assert campaign.review_scope_json["group_ids"] == ["case_metadata"]


def test_infeasible_no_fields_when_every_requested_group_is_exhausted(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    # Only a case_metadata field exists in the pool; neither requested group is present anywhere.
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(
            group_ids=["court_and_hearing", "cited_cases"], requested_case_count=1
        ),
    )
    assert set(result.fields_fully_exhausted) == {"court_and_hearing", "cited_cases"}
    assert result.feasibility == "infeasible_no_fields"


def test_same_case_different_fields_across_campaigns_is_allowed(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=2)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    case_metadata_campaign = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="campaign-case-metadata",
            campaign_name="Case metadata",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata"]),
            requested_case_count=1,
        ),
        request_id="req-1",
    )
    assert case_metadata_campaign.total_units == 1  # only the case_metadata unit for CAS-1

    all_fields_preview = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count=1),
    )
    assert all_fields_preview.feasibility == "feasible_exact"
    assert all_fields_preview.eligible_cases_count == 1
    assert all_fields_preview.overlap_cases_count == 1
    assert len(all_fields_preview.overlap_campaigns) == 1
    overlap = all_fields_preview.overlap_campaigns[0]
    assert overlap.campaign_key == "campaign-case-metadata"
    assert overlap.campaign_name == "Case metadata"
    assert [(item.group_id, item.cases_count) for item in overlap.group_counts] == [
        ("case_metadata", 1)
    ]

    court_campaign = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="campaign-court",
            campaign_name="Court and hearing",
            review_scope=CampaignReviewScopeInput(group_ids=["court_and_hearing"]),
            requested_case_count=1,
        ),
        request_id="req-2",
    )
    # The same case's *other* field is still available in the pool for a second campaign.
    assert court_campaign.total_units == 1
    assert court_campaign.not_ready_for_publish is False


def test_same_case_same_field_across_active_campaigns_is_blocked_by_pool_depletion(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    first = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="first-claim", campaign_name="First claim", requested_case_count=1
        ),
        request_id="req-1",
    )
    assert first.total_units == 1

    # A second campaign requesting the same (now-claimed) case_metadata field finds nothing left --
    # the conflict is structural (the row left the pool), not a raised exception.
    second_preview = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count=1),
    )
    assert second_preview.eligible_cases_count == 0
    assert second_preview.feasibility == "infeasible_no_cases"


def test_different_cases_with_all_available_fields_can_enter_different_campaigns(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Campaign ownership is scoped to (case, field group), never to a field globally."""

    sha = _sha()
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [_case("CAS-1", sha, groups=2), _case("CAS-2", sha, groups=2)],
    )
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    first = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="all-fields-first",
            campaign_name="All fields first",
            requested_case_count=1,
        ),
        request_id="req-all-fields-1",
    )
    second = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="all-fields-second",
            campaign_name="All fields second",
            requested_case_count=1,
        ),
        request_id="req-all-fields-2",
    )

    assert first.total_units == 2
    assert second.total_units == 2


def test_cases_all_only_selects_currently_eligible_pool_cases(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha), _case("CAS-2", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    first = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="all-first", campaign_name="All first", requested_case_count="all"
        ),
        request_id="req-1",
    )
    assert first.total_units == 4  # both cases, both groups

    # A second "all" request now finds nothing left in the pool -- not a stale/duplicated count.
    second_preview = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(requested_case_count="all"),
    )
    assert second_preview.eligible_cases_count == 0


def test_load_pool_cases_tops_up_a_draft_after_confirming_a_smaller_count(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    draft = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="top-up", campaign_name="Top up", requested_case_count=5
        ),
        request_id="req-1",
    )
    assert draft.not_ready_for_publish is True
    assert draft.total_units == 0

    topped_up = service.load_pool_cases(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=draft.campaign_id,
        body=LoadPoolCasesRequest(requested_case_count=5, confirm_smaller_count=True),
        request_id="req-2",
    )
    assert topped_up.not_ready_for_publish is False
    assert topped_up.materialized_cases == 1
    assert topped_up.materialized_units == 2
    assert topped_up.total_units == 2


def test_pool_import_writes_render_artifacts_for_every_pool_unit(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1)])
    unit_count = db_session.scalar(
        select(func.count()).select_from(ReviewUnit).where(ReviewUnit.tenant_id == admin.tenant_id)
    )
    artifact_count = db_session.scalar(
        select(func.count())
        .select_from(SourceRenderArtifact)
        .where(SourceRenderArtifact.tenant_id == admin.tenant_id)
    )
    assert unit_count == 1
    assert artifact_count == 1


def test_empty_field_scope_makes_every_pooled_case_eligible_whatever_groups_it_carries(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    # Heterogeneous pool: CAS-1 has only case_metadata, CAS-2 has case_metadata + court_and_hearing.
    # An empty scope declares no required groups, so BOTH cases are eligible. Resolving the empty
    # scope to the union of groups present in the pool would demand every case carry every group
    # and would strand CAS-1 -- the failure mode that made an "all fields" campaign import nothing.
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1), _case("CAS-2", sha)])
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(group_ids=[], requested_case_count=2),
    )
    assert result.feasibility == "feasible_exact"
    assert result.eligible_cases_count == 2
    assert result.eligible_review_units_count == 3  # 1 unit for CAS-1, 2 for CAS-2
    assert result.cases_available_for_some_selected_fields_only == 0
    assert result.unavailable_cases_count == 0
    assert result.fields_partially_available == []


def test_empty_scope_campaign_materializes_every_unit_of_every_selected_case(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1), _case("CAS-2", sha)])
    service = _service(tmp_path)
    response = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CreateCampaignRequest(
            campaign_key="all-fields", campaign_name="All fields", requested_case_count=2
        ),
        request_id="req-all-fields",
    )
    assert response.availability is not None
    assert response.availability.feasibility == "feasible_exact"
    assert response.not_ready_for_publish is False
    # Both cases move, with every unit they carry -- nothing is stranded in the pool.
    assert response.total_units == 3


def test_declared_field_scope_still_requires_a_case_to_have_every_requested_group(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    # The all-or-nothing rule is deliberate for a *declared* scope: a campaign must never promise a
    # field group it cannot supply for a case it selected.
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-1", sha, groups=1), _case("CAS-2", sha)])
    service = _service(tmp_path)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=_principal(db_session, admin),
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count=2
        ),
    )
    assert result.eligible_cases_count == 1  # only CAS-2
    assert result.cases_available_for_some_selected_fields_only == 1  # CAS-1


def test_null_scope_campaign_makes_non_matching_review_kind_units_eligible(
    db_session: Session,
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """ "All fields" campaigns store ``review_scope_json = NULL``; that must mean no narrowing.

    Regression for the bug where ``_eligible_units`` fell back to filtering by the policy's single
    ``review_kind`` (the web UI always sends ``"metadata_field"``) whenever a campaign had no
    declared scope. A unit whose ``review_kind`` is something else (e.g. ``cited_case``) must still
    be eligible for an unscoped campaign, exactly as it is for materialization
    (``_materialize_from_pool``, ``grouped_bundle``, ``queue``).
    """

    _ensure_admin_is_reviewer(db_session, admin)
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-NULLSCOPE-1", sha, groups=1)])
    review_service = _service(tmp_path)
    allocation_service = AllocationService("k" * 32)
    principal = _principal(db_session, admin)
    campaign = review_service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="null-scope-eligibility",
            campaign_name="Null scope eligibility",
            requested_case_count=1,
        ),
        request_id="req-nullscope-create",
    )
    assert campaign.review_scope is None
    assert campaign.total_units >= 1

    # Add a unit whose review_kind is not the policy's ("cited_case" instead of "metadata_field")
    # on the same subject -- exactly what a real relation unit looks like once a case has
    # cited-case or statute-reference units alongside its metadata_field units. review_kind is
    # immutable after insert (protect_review_unit_input), so a fresh row is required rather than
    # mutating an existing one.
    metadata_units = list(
        db_session.scalars(select(ReviewUnit).where(ReviewUnit.campaign_id == campaign.campaign_id))
    )
    assert metadata_units
    subject_id = metadata_units[0].review_subject_id
    relation_unit = ReviewUnit(
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        review_subject_id=subject_id,
        review_kind="cited_case",
        question="Confirm the cited case relation.",
        safe_field_label="Cited case",
        field_name=None,
        required_reviews=2,
        input_digest="0" * 64,
    )
    db_session.add(relation_unit)
    db_session.flush()

    eligible = allocation_service.preview_subjects(
        db_session,
        tenant_id=admin.tenant_id,
        campaign_id=campaign.campaign_id,
        principal=principal,
        body=SubjectPoolPreviewRequest(
            subject_kind="case",
            review_kind="metadata_field",
            selection_strategy="random",
            limit=10,
        ),
    )
    # Before the fix, an unscoped campaign filtered eligibility down to the policy's own
    # review_kind ("metadata_field"), so the "cited_case" unit would be silently dropped. It must
    # now be counted alongside the existing metadata_field units.
    assert eligible.eligible_subject_count == len(metadata_units) + 1
