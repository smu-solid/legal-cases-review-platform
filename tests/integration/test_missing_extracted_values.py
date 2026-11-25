"""Tests for missing extracted values as reviewable tasks.

1. ``related_cases`` stays fully selectable -- no exclusion allowlist.
2. Missing is hard-locked to "No": ``extraction_state='missing'`` can never be answered
   ``value_correct=true``, atomic or relation, no per-field legitimacy nuance.

Reuses the ``_seed_pool``/``_case``/``_service``/``_principal``/``_sha`` helpers from
``test_campaign_pool_availability.py`` rather than duplicating fixture wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit
from review_platform.review.schemas import (
    CampaignAvailabilityRequest,
    CampaignReviewScopeInput,
    CreateCampaignRequest,
    LoadPoolCasesRequest,
    ReviewItemAnswerInput,
)
from review_platform.review.state_machine import validate_item_answer
from tests.support.identities import AdminIdentity
from tests.support.pool import (
    _case,
    _principal,
    _seed_pool,
    _service,
    _sha,
)


def test_selecting_a_missing_group_does_not_shrink_eligibility(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """The owner's new rule: selecting more field groups never reduces eligible_cases_count."""

    sha = _sha()
    # CAS-1 has only case_metadata; CAS-2 has both groups. Without synthesis, requesting both
    # groups would drop CAS-1 (the pre-existing all-or-nothing rule, still the default below).
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-M1", sha, groups=1), _case("CAS-M2", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    without_synthesis = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count="all"
        ),
    )
    assert without_synthesis.eligible_cases_count == 1  # only CAS-M2, byte-for-byte old behaviour

    with_synthesis = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"],
            requested_case_count="all",
            synthesize_missing_values=True,
        ),
    )
    # Both cases are now eligible -- CAS-M1's missing court_and_hearing becomes a synthesis gap,
    # never an eligibility exclusion.
    assert with_synthesis.eligible_cases_count == 2


def test_synthesis_creates_missing_unit_and_is_idempotent_under_repeated_top_ups(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    # Two cases, both missing court_and_hearing -- CAS-S1 materializes at creation, CAS-S2 is
    # picked up by a later top-up (growing case_count), the realistic idempotent-top-up scenario:
    # a case whose real group already left the pool but whose missing-group synthesis must not
    # duplicate across repeated `load_pool_cases` calls that re-request it.
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [_case("CAS-S1", sha, groups=1), _case("CAS-S2", sha, groups=1)],
    )
    service = _service(tmp_path)
    principal = _principal(db_session, admin)

    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="synth-topup",
            campaign_name="Synth topup",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata", "court_and_hearing"]),
            requested_case_count=1,
            synthesize_missing_values=True,
        ),
        request_id="req-synth-1",
    )
    assert created.availability is not None
    assert created.availability.eligible_cases_count == 2
    # 1 real case_metadata unit + 1 synthesized court_and_hearing unit for the one selected case.
    assert created.total_units == 2

    campaign = db_session.scalar(
        select(Campaign).where(Campaign.tenant_id == admin.tenant_id, Campaign.key == "synth-topup")
    )
    assert campaign is not None
    units = db_session.scalars(
        select(ReviewUnit).where(
            ReviewUnit.tenant_id == admin.tenant_id, ReviewUnit.campaign_id == campaign.id
        )
    ).all()
    missing_units = [u for u in units if u.extraction_state == "missing"]
    assert len(missing_units) == 1
    assert missing_units[0].review_kind == "metadata_field"
    # Case heading bug fix: the synthesized subject must carry CAS-S1's real case title (from
    # _case()'s ``title="AA v BB"``), not the "No {group} extracted" placeholder -- that placeholder
    # belongs only at the field/item level (safe_field_label/question above), never as the
    # reviewer-facing case heading (queue.py / workspace / admin per-case table all derive the case
    # title from ReviewSubject.display_title).
    missing_subject = db_session.scalar(
        select(ReviewSubject).where(ReviewSubject.id == missing_units[0].review_subject_id)
    )
    assert missing_subject is not None
    assert missing_subject.display_title == "AA v BB"
    assert "No " not in missing_subject.display_title

    # Top up to both cases -- must add CAS-S2's units (real + synthesized) without duplicating
    # CAS-S1's already-synthesized unit.
    service.load_pool_cases(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        campaign_id=campaign.id,
        body=LoadPoolCasesRequest(requested_case_count=2, confirm_smaller_count=True),
        request_id="req-synth-topup-2",
    )
    units_after = db_session.scalars(
        select(ReviewUnit).where(
            ReviewUnit.tenant_id == admin.tenant_id, ReviewUnit.campaign_id == campaign.id
        )
    ).all()
    assert len(units_after) == 4  # CAS-S1's 2 units unchanged + CAS-S2's 2 new units
    assert sum(1 for u in units_after if u.extraction_state == "missing") == 2

    # Repeating the identical top-up again must not duplicate anything further (idempotent). Both
    # cases are already fully materialized, so the pool has nothing left for this scope -- the
    # request is correctly refused (no cases available), not silently re-run; either way no
    # duplicate row is ever created.
    with pytest.raises(APIError) as no_cases_error:
        service.load_pool_cases(
            db_session,
            tenant_id=admin.tenant_id,
            principal=principal,
            campaign_id=campaign.id,
            body=LoadPoolCasesRequest(requested_case_count=2, confirm_smaller_count=True),
            request_id="req-synth-topup-3",
        )
    units_final = db_session.scalars(
        select(ReviewUnit).where(
            ReviewUnit.tenant_id == admin.tenant_id, ReviewUnit.campaign_id == campaign.id
        )
    ).all()
    assert len(units_final) == 4
    assert sum(1 for u in units_final if u.extraction_state == "missing") == 2
    assert no_cases_error.value.code == "campaign_no_cases_available"


def test_present_only_campaign_is_unaffected_by_default(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Regression: synthesize_missing_values defaults to False -- existing flows unchanged."""

    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-R1", sha, groups=1), _case("CAS-R2", sha)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    result = service.preview_campaign_availability(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CampaignAvailabilityRequest(
            group_ids=["case_metadata", "court_and_hearing"], requested_case_count="all"
        ),
    )
    assert result.eligible_cases_count == 1  # CAS-M1-equivalent excluded, exactly as before
    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="present-only",
            campaign_name="Present only",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata", "court_and_hearing"]),
            requested_case_count=1,
        ),
        request_id="req-present-only",
    )
    assert created.total_units == 2  # both real fields of the one fully-eligible case
    units = db_session.scalars(
        select(ReviewUnit).where(ReviewUnit.tenant_id == admin.tenant_id)
    ).all()
    assert all(u.extraction_state == "present" for u in units)


def test_trigger_blocks_missing_present_flip(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    sha = _sha()
    _seed_pool(db_session, admin, tmp_path, [_case("CAS-T1", sha, groups=1)])
    service = _service(tmp_path)
    principal = _principal(db_session, admin)
    created = service.create_campaign(
        db_session,
        tenant_id=admin.tenant_id,
        principal=principal,
        body=CreateCampaignRequest(
            campaign_key="trigger-flip",
            campaign_name="Trigger flip",
            review_scope=CampaignReviewScopeInput(group_ids=["case_metadata", "court_and_hearing"]),
            requested_case_count=1,
            synthesize_missing_values=True,
        ),
        request_id="req-trigger-flip",
    )
    campaign = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id, Campaign.key == "trigger-flip"
        )
    )
    assert campaign is not None
    missing_unit = db_session.scalar(
        select(ReviewUnit).where(
            ReviewUnit.tenant_id == admin.tenant_id,
            ReviewUnit.campaign_id == campaign.id,
            ReviewUnit.extraction_state == "missing",
        )
    )
    assert missing_unit is not None
    db_session.flush()
    with (
        pytest.raises(Exception, match="review unit inputs are immutable"),
        db_session.begin_nested(),
    ):
        db_session.execute(
            text(
                "UPDATE review_platform.review_units SET extraction_state = 'present' "
                "WHERE id = :id"
            ),
            {"id": str(missing_unit.id)},
        )
    del created


def test_answer_submit_guard_rejects_correct_on_missing_unit() -> None:
    """Unit-level test of the server-side guard (state_machine.validate_item_answer)."""

    answer = ReviewItemAnswerInput(value_correct=True, provenance_correct=True)
    with pytest.raises(APIError) as exc_info:
        validate_item_answer(
            answer,
            state="submitted",
            allowed_evidence_ids=set(),
            extraction_state="missing",
        )
    assert exc_info.value.code == "missing_value_cannot_be_correct"


def test_answer_submit_guard_rejects_provenance_correct_on_missing_unit() -> None:
    """Both controls are locked: even value_correct=False, provenance_correct=True is rejected on a
    missing unit -- nothing was extracted, so there is no provenance to affirm either."""

    answer = ReviewItemAnswerInput(value_correct=False, provenance_correct=True)
    with pytest.raises(APIError) as exc_info:
        validate_item_answer(
            answer,
            state="submitted",
            allowed_evidence_ids=set(),
            extraction_state="missing",
        )
    assert exc_info.value.code == "missing_value_cannot_be_correct"


def test_answer_submit_guard_accepts_correction_on_missing_unit() -> None:
    answer = ReviewItemAnswerInput(
        value_correct=False,
        provenance_correct=False,
        corrected_value="the real value",
        corrected_value_display="the real value",
        failure_reason="value_incorrect",
    )
    # Must not raise for a correction path on a missing unit.
    validate_item_answer(
        answer,
        state="submitted",
        allowed_evidence_ids=set(),
        extraction_state="missing",
    )
