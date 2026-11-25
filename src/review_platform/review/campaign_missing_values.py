"""Idempotent creation of review tasks for missing extracted values."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.grouping import RELATION_GROUP_TO_REVIEW_KIND, classify_unit
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit, SourceSnapshot

_SYNTHETIC_MISSING_CONTRACT_VERSION = "review-platform-missing-value/v1"


def _synthesize_missing_unit(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign: Campaign,
    target_campaign: Campaign,
    case_id: str,
    source_system: str,
    group_id: str,
    required_reviews: int,
) -> None:
    """Insert one ``missing``-state ReviewUnit for ``case_id``'s ``group_id`` into the campaign.

    Idempotent under repeated top-ups: the synthesized ``SourceSnapshot`` uses a deterministic,
    case+group-scoped ``external_item_key`` (``uq_snapshot_external_item``), so a second call for
    the same case/group reuses the same snapshot/subject rather than creating a duplicate one, and
    ``uq_review_unit_input`` (``tenant_id, campaign_id, review_subject_id, review_kind``) then
    prevents a duplicate unit for that subject in this campaign. Mirrors the idempotent-top-up
    determinism ``materialize_from_pool``'s reassignment path already relies on."""

    # Never recreate a logical case/group already held by another campaign. Database uniqueness is
    # campaign-scoped, so this explicit ownership check is the cross-campaign invariant.
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    case_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    owned_rows = session.execute(
        select(
            ReviewUnit.review_kind,
            ReviewUnit.safe_field_label,
            ReviewUnit.field_name,
            ReviewUnit.campaign_id,
        )
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(
            ReviewUnit.tenant_id == tenant_id,
            case_col == case_id,
            source_col == source_system,
        )
    )
    for review_kind, safe_field_label, field_name, campaign_id in owned_rows:
        existing_group = classify_unit(review_kind, safe_field_label, field_name).group_id
        if existing_group != group_id:
            continue
        if campaign_id == target_campaign.id:
            return
        if campaign_id != pool_campaign.id:
            raise APIError(
                409,
                "campaign_field_overlap",
                "Requested fields already owned",
                "A requested case field group is already owned by another campaign. Refresh "
                "availability and try again.",
            )

    external_item_key = f"{source_system}:{case_id}:missing:{group_id}"[:240]
    snapshot = session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.tenant_id == tenant_id,
            SourceSnapshot.external_item_key == external_item_key,
        )
    )
    if snapshot is None:
        snapshot = SourceSnapshot(
            tenant_id=tenant_id,
            contract_version=_SYNTHETIC_MISSING_CONTRACT_VERSION,
            source_mode="dataset",
            source_version="missing",
            external_item_key=external_item_key,
            input_digest=digest_json({"case": case_id, "group": group_id, "missing": True}),
        )
        session.add(snapshot)
        session.flush()

    review_kind = RELATION_GROUP_TO_REVIEW_KIND.get(group_id, "metadata_field")
    subject = session.scalar(
        select(ReviewSubject).where(
            ReviewSubject.tenant_id == tenant_id,
            ReviewSubject.source_snapshot_id == snapshot.id,
        )
    )
    if subject is None:
        group_label = group_id.replace("_", " ")
        real_subjects = list(
            session.scalars(
                select(ReviewSubject)
                .join(
                    ReviewUnit,
                    (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
                    & (ReviewUnit.review_subject_id == ReviewSubject.id),
                )
                .where(
                    ReviewSubject.tenant_id == tenant_id,
                    ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
                    == case_id,
                    ReviewSubject.attributes_json["source_collection"].astext == source_system,
                    ReviewUnit.extraction_state == "present",
                )
            )
        )
        guarded = {
            (
                subject.attributes_json.get("source_collection"),
                subject.attributes_json.get("source_sha256"),
            )
            for subject in real_subjects
            if subject.attributes_json.get("source_sha256")
        }
        if len(guarded) != 1:
            raise APIError(
                409,
                "pool_identity_not_ready",
                "Pool identity not ready",
                "A missing-value review task cannot be created without one agreeing guarded "
                "case identity.",
            )
        real_subject = real_subjects[0] if real_subjects else None
        # Every real field/relation ReviewSubject for a case shares the same display_title/
        # display_subtitle (see the comment in campaign_lifecycle._campaign_cases), so any one
        # real subject gives us the case's real title. Reviewers should always see the real case
        # title as the heading; "No {group} extracted" belongs only at the field/item level (the
        # unit's safe_field_label/question below), never as the case-level heading. Fall back to
        # the placeholder only if the case has no real subject at all (edge case).
        if real_subject is not None:
            display_title = real_subject.display_title
            display_subtitle = real_subject.display_subtitle
        else:
            display_title = f"No {group_label} extracted"
            display_subtitle = group_label
        subject = ReviewSubject(
            tenant_id=tenant_id,
            source_snapshot_id=snapshot.id,
            subject_kind="case",
            external_subject_id=f"subject_{snapshot.id.hex}",
            display_title=display_title,
            display_subtitle=display_subtitle,
            source_version="missing",
            primary_source_ref=f"missing_{snapshot.id.hex[:32]}",
            attributes_json={
                "field_label": group_label,
                "snapshot_local_case_external_id": case_id,
                "source_collection": source_system,
                "source_sha256": next(iter(guarded))[1],
                "reference_semantics": "snapshot-local-soft-no-cross-database-fk",
                "synthesized_missing_group": group_id,
            },
        )
        session.add(subject)
        session.flush()

    existing_unit = session.scalar(
        select(ReviewUnit.id).where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == target_campaign.id,
            ReviewUnit.review_subject_id == subject.id,
            ReviewUnit.review_kind == review_kind,
        )
    )
    if existing_unit is not None:
        return  # already synthesized for this campaign by an earlier top-up

    unit = ReviewUnit(
        tenant_id=tenant_id,
        campaign_id=target_campaign.id,
        review_subject_id=subject.id,
        review_kind=review_kind,
        question=f"No {group_id.replace('_', ' ')} was extracted for this case. "
        "Confirm this is correct, or enter the correct value.",
        safe_field_label=group_id.replace("_", " "),
        field_name=None,
        required_reviews=required_reviews,
        input_digest=digest_json({"case": case_id, "group": group_id, "missing": True}),
        extraction_state="missing",
    )
    session.add(unit)
    session.flush()
