"""Caller-personalized adjudication campaign and case queue projections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.common.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from review_platform.review.adjudication_campaign_projections import (
    OrderedAdjudicationCase,
    adjudication_case_projections,
    case_counts,
)
from review_platform.review.adjudication_cases import adjudication_case_id
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    Campaign,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.schemas import (
    AdjudicationCampaignCaseQueuePage,
    AdjudicationCampaignQueuePage,
    AdjudicationCampaignSummary,
    AdjudicationCaseNeighbors,
)


class ReviewAdjudicationCampaignMixin(ReviewServiceBase):
    def adjudication_campaign_queue(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        request_id: str = "adjudication-campaign-queue",
    ) -> AdjudicationCampaignQueuePage:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        self._reconcile_inactive_adjudicators(session, tenant_id=tenant_id, request_id=request_id)
        campaigns = self._visible_adjudication_campaigns(
            session, tenant_id=tenant_id, adjudicator_id=principal.user.id
        )
        after = decode_cursor(cursor)
        if after is not None:
            after_key = (datetime.fromisoformat(str(after["created_at"])), str(after["id"]))
            campaigns = [
                campaign
                for campaign in campaigns
                if (campaign.created_at, str(campaign.id)) > after_key
            ]
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        has_more = len(campaigns) > limit
        page = campaigns[:limit]
        summaries = [
            self._campaign_summary(
                campaign,
                self._adjudication_case_projections(
                    session,
                    tenant_id=tenant_id,
                    campaign=campaign,
                    adjudicator_id=principal.user.id,
                ),
            )
            for campaign in page
        ]
        next_cursor = None
        if has_more and page:
            next_cursor = encode_cursor(
                {"created_at": page[-1].created_at.isoformat(), "id": str(page[-1].id)}
            )
        return AdjudicationCampaignQueuePage(
            campaigns=summaries, next_cursor=next_cursor, has_more=has_more
        )

    def adjudication_campaign_cases(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        status: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        request_id: str = "adjudication-campaign-cases",
    ) -> AdjudicationCampaignCaseQueuePage:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        self._reconcile_inactive_adjudicators(session, tenant_id=tenant_id, request_id=request_id)
        campaign = self._visible_adjudication_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            adjudicator_id=principal.user.id,
        )
        ordered = self._adjudication_case_projections(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            adjudicator_id=principal.user.id,
        )
        counts = case_counts(ordered)
        filtered = (
            ordered
            if status in (None, "all")
            else [row for row in ordered if row.item.status == status]
        )
        after = decode_cursor(cursor)
        if after is not None:
            after_key = (datetime.fromisoformat(str(after["created_at"])), str(after["case_id"]))
            filtered = [
                row for row in filtered if (row.first_created_at, row.item.case_id) > after_key
            ]
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        has_more = len(filtered) > limit
        page = filtered[:limit]
        next_cursor = None
        if has_more and page:
            next_cursor = encode_cursor(
                {
                    "created_at": page[-1].first_created_at.isoformat(),
                    "case_id": page[-1].item.case_id,
                }
            )
        return AdjudicationCampaignCaseQueuePage(
            campaign=self._campaign_summary(campaign, ordered),
            counts=counts,
            items=[row.item for row in page],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def adjudication_case_neighbors(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        anchor_adjudication_id: uuid.UUID,
        principal: Principal,
        request_id: str = "adjudication-case-neighbors",
    ) -> AdjudicationCaseNeighbors:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        self._reconcile_inactive_adjudicators(session, tenant_id=tenant_id, request_id=request_id)
        anchor = session.execute(
            select(Adjudication, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
                & (AdjudicationParticipation.adjudication_id == Adjudication.id),
            )
            .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == anchor_adjudication_id,
                ReviewUnit.campaign_id == campaign_id,
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status.in_(("pending", "submitted")),
            )
        ).first()
        if anchor is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        campaign = self._visible_adjudication_campaign(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            adjudicator_id=principal.user.id,
        )
        rows = self._adjudication_case_projections(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            adjudicator_id=principal.user.id,
        )
        anchor_case_id = adjudication_case_id(anchor[2])
        index = next((i for i, row in enumerate(rows) if row.item.case_id == anchor_case_id), None)
        if index is None:  # pragma: no cover - anchor belongs to campaign by query invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        previous_open = next(
            (row.item for row in reversed(rows[:index]) if row.item.workspace_adjudication_id),
            None,
        )
        next_open = next(
            (row.item for row in rows[index + 1 :] if row.item.workspace_adjudication_id),
            None,
        )
        return AdjudicationCaseNeighbors(previous_open=previous_open, next_open=next_open)

    def _visible_adjudication_campaigns(
        self, session: Session, *, tenant_id: uuid.UUID, adjudicator_id: uuid.UUID
    ) -> list[Campaign]:
        campaigns = list(
            session.scalars(
                select(Campaign)
                .where(Campaign.tenant_id == tenant_id, Campaign.status.not_in(("draft", "pool")))
                .order_by(Campaign.created_at, Campaign.id)
            )
        )
        participation_campaign_ids = set(
            session.scalars(
                select(ReviewUnit.campaign_id)
                .join(Adjudication, Adjudication.review_unit_id == ReviewUnit.id)
                .join(
                    AdjudicationParticipation,
                    AdjudicationParticipation.adjudication_id == Adjudication.id,
                )
                .where(
                    ReviewUnit.tenant_id == tenant_id,
                    AdjudicationParticipation.adjudicator_id == adjudicator_id,
                )
                .distinct()
            )
        )
        return [
            campaign
            for campaign in campaigns
            if campaign.status != "closed" or campaign.id in participation_campaign_ids
        ]

    def _visible_adjudication_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        adjudicator_id: uuid.UUID,
    ) -> Campaign:
        campaign = next(
            (
                item
                for item in self._visible_adjudication_campaigns(
                    session, tenant_id=tenant_id, adjudicator_id=adjudicator_id
                )
                if item.id == campaign_id
            ),
            None,
        )
        if campaign is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return campaign

    @staticmethod
    def _adjudication_case_projections(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign: Campaign,
        adjudicator_id: uuid.UUID,
    ) -> list[OrderedAdjudicationCase]:
        return adjudication_case_projections(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            adjudicator_id=adjudicator_id,
        )

    @staticmethod
    def _campaign_summary(
        campaign: Campaign, rows: list[OrderedAdjudicationCase]
    ) -> AdjudicationCampaignSummary:
        counts = case_counts(rows)
        return AdjudicationCampaignSummary(
            campaign_id=campaign.id,
            campaign_key=campaign.key,
            campaign_name=campaign.name,
            waiting_count=counts.waiting,
            in_progress_count=counts.in_progress,
            finished_count=counts.finished,
            not_required_count=counts.not_required,
            total_case_count=counts.all,
        )
