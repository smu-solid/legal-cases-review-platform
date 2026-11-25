from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from review_platform.review.allocation.eligible_units import EligibleUnit
from review_platform.review.allocation.selection import subject_metrics
from review_platform.review.allocation.service import AllocationService
from review_platform.review.grouping import classify_unit
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit, SourceSnapshot
from tests.support.identities import AdminIdentity


def _legacy_eligible_units(
    session: Session, *, tenant_id: uuid.UUID, campaign: Campaign
) -> list[tuple[ReviewUnit, ReviewSubject]]:
    blocked = aliased(ReviewUnit)
    subject_blocked = exists(
        select(1).where(
            blocked.tenant_id == tenant_id,
            blocked.campaign_id == campaign.id,
            blocked.review_subject_id == ReviewUnit.review_subject_id,
            blocked.status.in_(("in_adjudication", "resolved")),
        )
    )
    rows = session.execute(
        select(ReviewUnit, ReviewSubject)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == campaign.id,
            ReviewUnit.status.in_(("pending", "in_review")),
            ~subject_blocked,
            ReviewSubject.subject_kind == "case",
        )
        .order_by(ReviewUnit.id)
    ).all()
    if not campaign.review_scope_json:
        return list(rows)
    group_ids = set(campaign.review_scope_json.get("group_ids") or [])
    review_kinds = set(campaign.review_scope_json.get("review_kinds") or [])
    return [
        (unit, subject)
        for unit, subject in rows
        if (
            not group_ids
            or classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name).group_id
            in group_ids
        )
        and (not review_kinds or unit.review_kind in review_kinds)
    ]


def _project_legacy(unit: ReviewUnit, subject: ReviewSubject) -> EligibleUnit:
    attributes = subject.attributes_json or {}
    return EligibleUnit(
        review_unit_id=unit.id,
        review_subject_id=subject.id,
        tenant_id=unit.tenant_id,
        campaign_id=unit.campaign_id,
        status=unit.status,
        subject_kind=subject.subject_kind,
        review_kind=unit.review_kind,
        safe_field_label=unit.safe_field_label,
        field_name=unit.field_name,
        snapshot_local_case_external_id=attributes.get("snapshot_local_case_external_id"),
        external_subject_id=subject.external_subject_id,
        citation_metrics=attributes.get("citation_metrics"),
        display_title=subject.display_title,
    )


def _add_subject(
    session: Session,
    *,
    admin: AdminIdentity,
    campaign: Campaign,
    suffix: str,
    case_id: str | None,
    units: list[tuple[str, str, str | None, str]],
) -> None:
    snapshot = SourceSnapshot(
        tenant_id=admin.tenant_id,
        contract_version="projection-test/v1",
        source_version="projection-test",
        external_item_key=f"projection:{suffix}",
        input_digest=f"projection-snapshot-{suffix}",
    )
    session.add(snapshot)
    session.flush()
    attributes: dict[str, object] = {"citation_metrics": {"inbound_count": 7, "outbound_count": 3}}
    if case_id is not None:
        attributes["snapshot_local_case_external_id"] = case_id
    subject = ReviewSubject(
        tenant_id=admin.tenant_id,
        source_snapshot_id=snapshot.id,
        subject_kind="case",
        external_subject_id=f"external-{suffix}",
        display_title=f"Projection {suffix}",
        primary_source_ref=f"projection-ref-{suffix}",
        attributes_json=attributes,
    )
    session.add(subject)
    session.flush()
    for review_kind, label, field_name, status in units:
        session.add(
            ReviewUnit(
                tenant_id=admin.tenant_id,
                campaign_id=campaign.id,
                review_subject_id=subject.id,
                review_kind=review_kind,
                question=f"Review {label}",
                safe_field_label=label,
                field_name=field_name,
                status=status,
                input_digest=f"projection-unit-{suffix}-{review_kind}",
            )
        )
    session.flush()


def test_eligible_projection_matches_legacy_rows_for_all_and_scoped_campaigns(
    db_session: Session, admin: AdminIdentity
) -> None:
    campaign = Campaign(
        tenant_id=admin.tenant_id,
        key="eligible-projection-parity",
        name="Eligible projection parity",
        status="draft",
        subject_kind="case",
        review_kind="metadata_field",
        policy_json={},
        review_scope_json=None,
        manifest_digest="eligible-projection-parity",
        created_by=admin.user_id,
    )
    db_session.add(campaign)
    db_session.flush()
    _add_subject(
        db_session,
        admin=admin,
        campaign=campaign,
        suffix="case",
        case_id="CASE-PROJECTION-1",
        units=[
            ("metadata_field", "Citation Neutral", "cases.citation_neutral", "pending"),
            ("cited_case", "Cited case", None, "in_review"),
        ],
    )
    _add_subject(
        db_session,
        admin=admin,
        campaign=campaign,
        suffix="fallback",
        case_id=None,
        units=[("metadata_field", "Court", "cases.court", "pending")],
    )
    _add_subject(
        db_session,
        admin=admin,
        campaign=campaign,
        suffix="blocked",
        case_id="CASE-PROJECTION-BLOCKED",
        units=[
            ("metadata_field", "Title Raw", "cases.title_raw", "pending"),
            ("cited_case", "Cited case", None, "resolved"),
        ],
    )

    service = AllocationService("projection-test-key")

    def assert_parity() -> list[EligibleUnit]:
        legacy = _legacy_eligible_units(db_session, tenant_id=admin.tenant_id, campaign=campaign)
        expected = [_project_legacy(unit, subject) for unit, subject in legacy]
        projected = service._eligible_units(
            db_session,
            tenant_id=admin.tenant_id,
            campaign_id=campaign.id,
            subject_kind="case",
            review_kind="metadata_field",
        )
        assert projected == expected
        assert [unit.review_unit_id for unit in projected] == [unit.id for unit, _ in legacy]
        assert [
            classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name).group_id
            for unit in projected
        ] == [
            classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name).group_id
            for unit, _ in legacy
        ]
        assert service._group_units_by_case(projected) == service._group_units_by_case(expected)
        assert service._snapshot_digest(projected) == service._snapshot_digest(expected)
        assert [subject_metrics(unit) for unit in projected] == [
            {"inbound_count": 7.0, "outbound_count": 3.0} for _ in projected
        ]
        return projected

    all_fields = assert_parity()
    assert {unit.case_key for unit in all_fields} == {
        "CASE-PROJECTION-1",
        "subject:external-fallback",
    }
    assert all(unit.case_key != "CASE-PROJECTION-BLOCKED" for unit in all_fields)

    metadata_group = classify_unit(
        "metadata_field", "Citation Neutral", "cases.citation_neutral"
    ).group_id
    campaign.review_scope_json = {
        "group_ids": [metadata_group],
        "review_kinds": ["metadata_field"],
        "source_families": [],
    }
    db_session.flush()
    scoped = assert_parity()
    assert [(unit.case_key, unit.safe_field_label) for unit in scoped] == [
        ("CASE-PROJECTION-1", "Citation Neutral")
    ]
