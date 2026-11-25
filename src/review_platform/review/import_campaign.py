"""Campaign identity and cross-campaign case/field conflict checks."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.json import digest_json
from review_platform.dataset.types import InputCase
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.campaign_conflicts import (
    CaseFieldCandidate,
    conflict_detail_payload,
    find_case_field_conflicts,
)
from review_platform.review.grouping import scope_matches
from review_platform.review.import_source import DatasetImportError, _field_label
from review_platform.review.models import Campaign


def _check_case_field_conflicts(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    cases: list[InputCase],
) -> None:
    """Check case field conflicts."""

    candidates = []
    for case in cases:
        for field in case.fields:
            label = _field_label(field.field_name)
            if scope_matches(
                "metadata_field",
                label,
                campaign.review_scope_json,
                source_system=case.source_system,
                field_name=field.field_name,
            ):
                candidates.append(
                    CaseFieldCandidate(
                        case_id=case.external_id,
                        review_kind="metadata_field",
                        safe_field_label=label,
                    )
                )
        for relation in case.relations:
            if scope_matches(
                relation.review_kind,
                relation.display_label,
                campaign.review_scope_json,
                source_system=case.source_system,
            ):
                candidates.append(
                    CaseFieldCandidate(
                        case_id=case.external_id,
                        review_kind=relation.review_kind,
                        safe_field_label=relation.display_label,
                    )
                )
    conflicts = find_case_field_conflicts(
        session,
        tenant_id=tenant_id,
        exclude_campaign_id=campaign.id,
        candidates=candidates,
    )
    if conflicts:
        raise DatasetImportError(
            "Cannot import: the following case/field groups are already assigned to another "
            f"active campaign: {conflict_detail_payload(conflicts)}"
        )


def _get_or_create_campaign(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    key: str,
    name: str,
    source_system: str,
    cases: list[InputCase],
    review_scope: dict[str, list[str]] | None = None,
    minimum_reviews_per_case: int | None = None,
    campaign_status: str = "draft",
) -> Campaign:
    campaign = session.scalar(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.key == key)
    )
    if campaign is not None:
        return campaign
    manifest_digest = digest_json(
        {"source_system": source_system, "case_ids": [case.external_id for case in cases]}
    )
    campaign = Campaign(
        tenant_id=tenant_id,
        key=key,
        name=name,
        # Preload into the reserved pool; other imports start as editable drafts.
        status=campaign_status,
        policy_version="dataset-v1",
        policy_json={
            "minimum_reviews_per_case": resolve_minimum_reviews_per_case(minimum_reviews_per_case),
            "blocked_units": 0,
            "contains_dataset_input": True,
        },
        review_scope_json=review_scope or None,
        manifest_digest=manifest_digest,
        created_by=created_by,
    )
    session.add(campaign)
    session.flush()
    return campaign
