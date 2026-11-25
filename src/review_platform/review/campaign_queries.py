"""Campaign reads, persisted policy interpretation, and detail projection."""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.db.models import AuditEvent
from review_platform.review.campaign_allocation_math import (
    MINIMUM_REVIEWS_PER_CASE_DEFAULT,
    CampaignCase,
)
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit
from review_platform.review.schemas import (
    CampaignCaseFilter,
    CampaignDetailResponse,
    CampaignReviewScopeInput,
)

# Completion is derived from this audit event; it is not a campaign status transition.
CAMPAIGN_MARKED_COMPLETED_EVENT = "campaign.marked_completed"


def _load_campaign(session: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign:
    campaign = session.scalar(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
    )
    if campaign is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    return campaign


def _load_campaign_for_update(
    session: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = session.scalar(
        select(Campaign)
        .where(Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
        .with_for_update()
    )
    if campaign is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    return campaign


def _campaign_cases(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[CampaignCase]:
    """Distinct real-world cases in a campaign, grouped by ``snapshot_local_case_external_id``."""

    case_id_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    rows = session.execute(
        select(
            case_id_col.label("case_external_id"),
            # Postgres has no MIN(uuid) aggregate -- pick the lexicographically smallest id via a
            # text cast, then parse it back. Only used as an opaque, stable representative id for
            # this read-only preview plan, never persisted.
            func.min(cast(ReviewSubject.id, String)).label("review_subject_id"),
            func.min(ReviewSubject.display_title).label("display_title"),
        )
        .select_from(ReviewSubject)
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
            & (ReviewUnit.review_subject_id == ReviewSubject.id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign_id)
        .group_by(case_id_col)
        .order_by(case_id_col)
    ).all()
    return [
        CampaignCase(
            review_subject_id=uuid.UUID(row.review_subject_id),
            display_title=row.display_title,
            case_external_id=row.case_external_id,
        )
        for row in rows
    ]


def _selected_reviewer_ids(campaign: Campaign) -> list[uuid.UUID]:
    """Read the campaign's persisted reviewer selection from ``policy_json``."""

    raw = (campaign.policy_json or {}).get("selected_reviewer_ids", [])
    return [uuid.UUID(str(value)) for value in raw]


def _minimum_reviews_per_case(campaign: Campaign) -> int:
    """Read the campaign's persisted minimum-reviews-per-case policy, defaulting to 2."""

    return int(
        (campaign.policy_json or {}).get(
            "minimum_reviews_per_case", MINIMUM_REVIEWS_PER_CASE_DEFAULT
        )
    )


def _campaign_review_scope(campaign: Campaign) -> CampaignReviewScopeInput | None:
    if not campaign.review_scope_json:
        return None
    return CampaignReviewScopeInput.model_validate(campaign.review_scope_json)


def _campaign_detail_response(session: Session, campaign: Campaign) -> CampaignDetailResponse:
    total_units = (
        session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == campaign.tenant_id, ReviewUnit.campaign_id == campaign.id
            )
        )
        or 0
    )
    policy = campaign.policy_json or {}
    return CampaignDetailResponse(
        campaign_id=campaign.id,
        campaign_key=campaign.key,
        campaign_name=campaign.name,
        status=campaign.status,
        review_scope=_campaign_review_scope(campaign),
        reviews_per_case=_minimum_reviews_per_case(campaign),
        selected_reviewer_ids=_selected_reviewer_ids(campaign),
        total_units=total_units,
        synthesize_missing_values=bool(policy.get("synthesize_missing_values", False)),
        case_filter=CampaignCaseFilter.model_validate(
            policy.get("case_filter") or {"version": "v1", "all": []}
        ),
        case_id_selection=policy.get("case_id_selection"),
        case_id_selection_file_name=policy.get("case_id_selection_file_name"),
        completed=_campaign_completed(session, campaign.id),
    )


def _campaign_completed(session: Session, campaign_id: uuid.UUID) -> bool:
    """A campaign is "completed" iff a ``CAMPAIGN_MARKED_COMPLETED_EVENT`` audit event exists for
    it. ``AuditEvent`` has no ``tenant_id`` column (it is a global, hash-chained table) but
    ``object_id`` is a campaign UUID, already globally unique, so this cannot cross tenants.
    """

    return (
        session.scalar(
            select(AuditEvent.id)
            .where(
                AuditEvent.object_type == "campaign",
                AuditEvent.object_id == str(campaign_id),
                AuditEvent.event_type == CAMPAIGN_MARKED_COMPLETED_EVENT,
            )
            .limit(1)
        )
        is not None
    )
