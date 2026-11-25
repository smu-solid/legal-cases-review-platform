from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.dataset.types import (
    InputCandidate,
    InputField,
)
from review_platform.review.dataset_import import DatasetImportError
from review_platform.review.models import (
    Assignment,
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewUnit,
    SourceRenderArtifact,
    SourceSnapshot,
)
from tests.support.identities import AdminIdentity
from tests.support.import_cases import (
    _PRESENT_SNIPPET,
    _SAMPLE_A_FIXTURE,
    _SAMPLE_B_FIXTURE,
    _candidate,
    _cited_case_relation,
    _evidence,
    _import,
    _import_source,
    _real_case,
    _reviewer,
    _sample_b_case,
    _service,
)


def test_real_import_writes_real_rows(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    result = _import(db_session, admin, tmp_path)
    assert result.imported_units == 1  # type: ignore[attr-defined]
    assert result.imported_cases == 1  # type: ignore[attr-defined]
    snapshot = db_session.scalar(
        select(SourceSnapshot).where(SourceSnapshot.tenant_id == admin.tenant_id)
    )
    assert snapshot is not None and snapshot.source_mode == "dataset"
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == 1
    assert db_session.scalar(select(func.count()).select_from(SourceRenderArtifact)) == 1
    labels = set(db_session.scalars(select(Candidate.label)).all())
    assert labels == {"A", "B"}  # deterministic + model


def test_real_import_creates_campaign_as_draft(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    result = _import(db_session, admin, tmp_path)
    campaign = db_session.scalar(
        select(Campaign).where(Campaign.id == result.campaign_id)  # type: ignore[attr-defined]
    )
    assert campaign is not None and campaign.status == "draft"


def test_real_import_is_idempotent(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    _import(db_session, admin, tmp_path)
    again = _import(db_session, admin, tmp_path)
    assert again.imported_units == 0  # type: ignore[attr-defined]
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == 1


def test_unresolved_case_is_counted_and_named(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A case whose raw source cannot be resolved is skipped, counted, and NAMED in the result,
    so a fail-closed exit-3 run identifies its casualties instead of reporting a bare count."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    ghost = replace(_real_case(sha256), external_id="CAS-GHOST-1", sha256="f" * 64)
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-ghost",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[ghost, _real_case(sha256)],
    )
    assert result.unresolved_source_cases == 1
    assert result.unresolved_case_ids == ["CAS-GHOST-1"]
    assert result.imported_cases == 1  # the resolvable case still lands


def test_real_import_tops_up_existing_campaign_with_new_cases(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A repeated dataset import with a larger case list must add
    only the cases not yet present: `_get_or_create_campaign` reuses the existing campaign (no
    manifest-digest guard, unlike the synthetic importer before its own top-up fix) and
    `_persist_unit` skips any case/field already imported by its `external_item_key`, so re-running
    with CASES=N > the campaign's current count tops it up rather than erroring or re-importing
    everything."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    first_case = _real_case(sha256)
    second_case = replace(
        first_case,
        external_id="CAS-TEST-2",
        source_document_id="SRC-TEST-2",
        title="CC v DD",
    )

    first = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-topup",
        campaign_name="Real Review Topup",
        source_system="sample_a",
        cases=[first_case],
    )
    assert first.imported_units == 1  # type: ignore[attr-defined]
    assert first.imported_cases == 1  # type: ignore[attr-defined]

    topped_up = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-topup",
        campaign_name="Real Review Topup",
        source_system="sample_a",
        cases=[first_case, second_case],
    )
    assert topped_up.campaign_id == first.campaign_id  # type: ignore[attr-defined]
    # Only the new case's field is newly imported -- first_case is already present and skipped.
    assert topped_up.imported_units == 1  # type: ignore[attr-defined]
    assert topped_up.imported_cases == 1  # type: ignore[attr-defined]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(ReviewUnit.campaign_id == first.campaign_id)  # type: ignore[attr-defined]
        )
        == 2
    )


def test_real_import_serializes_date_candidate_values(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    case.fields[0] = InputField(
        field_name="cases.j_date",
        display_value="2020-01-02",
        value_candidate=InputCandidate(
            source_kind="deterministic",
            verdict="supported",
            value=date(2020, 1, 2),
            rationale="date from reviewer_case",
            supporting_quote=None,
        ),
        model_candidate=None,
        evidence=[_evidence(_PRESENT_SNIPPET)],
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-date",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    candidate = db_session.scalar(select(Candidate))
    assert candidate is not None
    assert candidate.value_json == "2020-01-02"


def test_real_import_applies_review_scope(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A scoped real campaign imports only in-scope fields and persists its scope."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    # Two fields in different groups: citation_neutral -> case_metadata, court -> court_and_hearing.
    case.fields.append(
        InputField(
            field_name="cases.court",
            display_value="SGHCF",
            value_candidate=_candidate("deterministic", "SGHCF"),
            model_candidate=_candidate("model", "SGHCF"),
            evidence=[_evidence(_PRESENT_SNIPPET)],
        )
    )
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-scoped",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
        review_scope={"group_ids": ["case_metadata"], "review_kinds": []},
    )
    # Only the case_metadata field is in scope.
    assert result.imported_units == 1
    labels = list(db_session.scalars(select(ReviewUnit.safe_field_label)).all())
    assert labels == ["Citation Neutral"]
    campaign = db_session.scalar(select(Campaign).where(Campaign.key == "real-sample_a-scoped"))
    assert campaign is not None
    assert campaign.review_scope_json == {"group_ids": ["case_metadata"], "review_kinds": []}


def test_real_import_writes_relation_units(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A provenance-backed cited-case relation becomes its own review unit alongside the field."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    case.relations.append(_cited_case_relation())
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-rel",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    assert result.imported_units == 2  # 1 metadata field + 1 relation
    kinds = set(db_session.scalars(select(ReviewUnit.review_kind)).all())
    assert kinds == {"metadata_field", "cited_case"}
    relation_unit = db_session.scalar(
        select(ReviewUnit).where(ReviewUnit.review_kind == "cited_case")
    )
    assert relation_unit is not None and relation_unit.safe_field_label == "Cited case"
    # Relation units carry a single deterministic candidate (no model/validator pair) that survives.
    relation_candidates = db_session.scalars(
        select(Candidate.label).where(Candidate.review_unit_id == relation_unit.id)
    ).all()
    assert list(relation_candidates) == ["A"]
    window = db_session.scalar(
        select(EvidenceWindow).where(EvidenceWindow.review_unit_id == relation_unit.id)
    )
    assert window is not None and window.char_start is not None  # relation evidence re-anchored


def test_review_scope_can_select_relation_kinds_only(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A scope of review_kinds=[cited_case] imports the relation unit but skips metadata fields."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    case.relations.append(_cited_case_relation())
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-rel-scope",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
        review_scope={"group_ids": [], "review_kinds": ["cited_case"]},
    )
    assert result.imported_units == 1
    kinds = list(db_session.scalars(select(ReviewUnit.review_kind)).all())
    assert kinds == ["cited_case"]


def test_real_import_rejects_case_field_conflict_across_active_campaigns(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test real import rejects case field conflict across active campaigns."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-conflict-first",
        campaign_name="Real Review (first)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
        review_scope={"group_ids": ["case_metadata"], "review_kinds": []},
    )
    with pytest.raises(DatasetImportError):
        service.import_cases(
            db_session,
            tenant_id=admin.tenant_id,
            created_by=admin.user_id,
            campaign_key="real-conflict-second",
            campaign_name="Real Review (second)",
            source_system="sample_a",
            cases=[_real_case(sha256)],
            review_scope={"group_ids": ["case_metadata"], "review_kinds": []},
        )
    # No review units were written for the rejected second campaign.
    second = db_session.scalar(select(Campaign).where(Campaign.key == "real-conflict-second"))
    assert second is not None
    unit_count = db_session.scalar(
        select(func.count()).select_from(ReviewUnit).where(ReviewUnit.campaign_id == second.id)
    )
    assert unit_count == 0


def test_real_import_allows_disjoint_field_group_for_same_case(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test real import allows disjoint field group for same case."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-disjoint-first",
        campaign_name="Real Review (first)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
        review_scope={"group_ids": ["case_metadata"], "review_kinds": []},
    )
    case_with_relation = _real_case(sha256)
    case_with_relation.relations.append(_cited_case_relation())
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-disjoint-second",
        campaign_name="Real Review (second)",
        source_system="sample_a",
        cases=[case_with_relation],
        review_scope={"group_ids": [], "review_kinds": ["cited_case"]},
    )
    assert result.imported_units == 1
    kinds = list(
        db_session.scalars(
            select(ReviewUnit.review_kind).where(ReviewUnit.campaign_id == result.campaign_id)
        ).all()
    )
    assert kinds == ["cited_case"]


def test_real_import_allows_multiple_reviewers_for_same_case_field_within_campaign(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test real import allows multiple reviewers for same case field within campaign."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-multi-reviewer",
        campaign_name="Real Review (multi-reviewer)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
        review_scope={"group_ids": ["case_metadata"], "review_kinds": []},
    )
    unit_id = db_session.scalar(
        select(ReviewUnit.id).where(ReviewUnit.campaign_id == result.campaign_id)
    )
    assert unit_id is not None

    reviewer_ids = [_reviewer(db_session, admin, suffix=str(index)) for index in range(2)]
    lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
    for reviewer_id in reviewer_ids:
        db_session.add(
            Assignment(
                tenant_id=admin.tenant_id,
                review_unit_id=unit_id,
                reviewer_id=reviewer_id,
                lease_expires_at=lease_expires_at,
            )
        )
    db_session.flush()

    assignment_count = db_session.scalar(
        select(func.count()).select_from(Assignment).where(Assignment.review_unit_id == unit_id)
    )
    assert assignment_count == len(reviewer_ids) == 2


def test_real_import_defaults_required_reviews_to_two(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    result = _import(db_session, admin, tmp_path)
    campaign = db_session.scalar(
        select(Campaign).where(Campaign.id == result.campaign_id)  # type: ignore[attr-defined]
    )
    assert campaign is not None
    assert campaign.policy_json["minimum_reviews_per_case"] == 2
    unit = db_session.scalar(select(ReviewUnit))
    assert unit is not None and unit.required_reviews == 2


def test_real_import_honors_configured_minimum_reviews_per_case(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-min-reviews",
        campaign_name="Real Review (configured minimum)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
        minimum_reviews_per_case=3,
    )
    campaign = db_session.scalar(select(Campaign).where(Campaign.id == result.campaign_id))
    assert campaign is not None
    assert campaign.policy_json["minimum_reviews_per_case"] == 3
    unit = db_session.scalar(select(ReviewUnit).where(ReviewUnit.campaign_id == result.campaign_id))
    assert unit is not None and unit.required_reviews == 3


def test_real_import_reuses_existing_campaigns_minimum_reviews_per_case(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A second import into an already-created campaign uses its persisted value, not a
    different value passed on the later call, so required_reviews never mixes within a campaign
    (mirrors how review_scope is applied)."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    first = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-min-reviews-reuse",
        campaign_name="Real Review (reuse)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
        minimum_reviews_per_case=4,
    )
    second_case = replace(_real_case(sha256), external_id="CAS-TEST-2")
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-min-reviews-reuse",
        campaign_name="Real Review (reuse)",
        source_system="sample_a",
        cases=[second_case],
        minimum_reviews_per_case=2,
    )
    units = db_session.scalars(
        select(ReviewUnit.required_reviews).where(ReviewUnit.campaign_id == first.campaign_id)
    ).all()
    assert list(units) == [4, 4]


def test_multi_source_seed_shares_one_campaign(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A Sample A + Sample B pilot imports both sources into ONE campaign visible to the admin.

    This is the multi-source seed behaviour the dataset importer orchestrates: two per-source
    imports keyed     by the same ``campaign_key`` land under a single campaign (the
    importer's get-or-create keeps it     one), so ``getCampaignProgress`` shows the whole
    pilot as a single row."""

    sample_a = _import_source(
        db_session,
        admin,
        tmp_path,
        fixture=_SAMPLE_A_FIXTURE,
        source_system="sample_a",
        build_case=_real_case,
        key="real-pilot",
    )
    sample_b = _import_source(
        db_session,
        admin,
        tmp_path,
        fixture=_SAMPLE_B_FIXTURE,
        source_system="sample_b",
        build_case=_sample_b_case,
        key="real-pilot",
    )
    # Both source imports resolve to the same campaign.
    assert sample_a.campaign_id == sample_b.campaign_id  # type: ignore[attr-defined]
    campaigns = db_session.scalars(
        select(Campaign).where(Campaign.tenant_id == admin.tenant_id)
    ).all()
    assert len(campaigns) == 1 and campaigns[0].key == "real-pilot"
    # Both source families are represented under the one campaign.
    systems = set(db_session.scalars(select(SourceRenderArtifact.source_system)).all())
    assert systems == {"sample_a", "sample_b"}
    unit_count = db_session.scalar(
        select(func.count())
        .select_from(ReviewUnit)
        .where(ReviewUnit.campaign_id == campaigns[0].id)
    )
    imported = sample_a.imported_units + sample_b.imported_units  # type: ignore[attr-defined]
    assert unit_count == imported >= 2  # the admin campaign summary aggregates both sources
