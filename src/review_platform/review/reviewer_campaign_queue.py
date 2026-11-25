"""Reviewer campaign summaries with case-level completion counts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Campaign,
    CaseSubmission,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.proposal_scope import proposal_counts
from review_platform.review.queue_identity import _case_id, _selected_group_ids
from review_platform.review.reviewer_case_queue import ReviewerCaseQueueMixin
from review_platform.review.schemas import (
    ReviewerCampaignQueuePage,
    ReviewerCampaignSummary,
)


class ReviewerCampaignQueueMixin(ReviewerCaseQueueMixin):
    def campaign_queue(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ReviewerCampaignQueuePage:
        """Campaign-grouped queue summary: one card per campaign the reviewer is assigned to.

        Counts are this reviewer's own work only. ``selected_group_ids`` reflects the campaign's
        review-scope field-group restriction (every group when the campaign is unrestricted), never
        a source-family label -- Sample A/Sample B are never surfaced to the reviewer. Keyset-
        paginated by ``(created_at, id)`` (the same stable order the cards render in) so a reviewer
        assigned to many campaigns never loads them all at once.
        """

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        allowed_campaign_ids = self._reviewer_campaign_ids(
            session, tenant_id=tenant_id, reviewer_id=principal.user.id
        )
        if not allowed_campaign_ids:
            return ReviewerCampaignQueuePage(campaigns=[])
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        stmt = (
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id, Campaign.id.in_(allowed_campaign_ids))
            .order_by(Campaign.created_at, Campaign.id)
        )
        after = decode_cursor(cursor)
        if after is not None:
            stmt = stmt.where(
                tuple_(Campaign.created_at, Campaign.id)
                > (datetime.fromisoformat(str(after["created_at"])), uuid.UUID(str(after["id"])))
            )
        campaigns = list(session.scalars(stmt.limit(limit + 1)).all())
        has_more = len(campaigns) > limit
        campaigns = campaigns[:limit]
        summaries = [
            ReviewerCampaignSummary(
                campaign_id=campaign.id,
                campaign_key=campaign.key,
                campaign_name=campaign.name,
                **self._case_granular_campaign_counts(
                    session, tenant_id=tenant_id, principal=principal, campaign_id=campaign.id
                ),
                selected_group_ids=_selected_group_ids(campaign),
            )
            for campaign in campaigns
        ]
        next_cursor = (
            encode_cursor(
                {"created_at": campaigns[-1].created_at.isoformat(), "id": str(campaigns[-1].id)}
            )
            if has_more and campaigns
            else None
        )
        return ReviewerCampaignQueuePage(
            campaigns=summaries, next_cursor=next_cursor, has_more=has_more
        )

    def _case_granular_campaign_counts(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
    ) -> dict[str, int]:
        """Case-grouped not_started/in_progress/completed counts for one campaign.

        Counts distinct **assigned cases**, not every case merely present in the campaign: a case
        with ten fields, nine
        submitted, is one "in_progress" case, not nine "completed" units and one open. A case
        counts as "completed" only once its explicit :class:`CaseSubmission` row exists for this
        reviewer (not merely because every owned field happens to be individually submitted --
        see that model's docstring); "in_progress" means the reviewer holds at least one
        claimed/submitted assignment on the case but hasn't submitted the case itself yet;
        "not_started" means assignments exist for the reviewer but no answer draft has been saved.
        Unallocated campaign cases are intentionally absent from a reviewer's personal counts, and
        so are cases the reviewer holds only ``released`` rows on: a rebalance moved that work to
        someone else, so counting it told a reviewer who had finished all ten of her cases that she
        was on 10/15 (see ``assignment_status.assignment_is_live``).
        """

        rows = session.execute(
            select(ReviewSubject, Assignment.id, Assignment.status)
            .select_from(Assignment)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.reviewer_id == principal.user.id,
                ReviewUnit.campaign_id == campaign_id,
                assignment_is_live(),
            )
        ).all()
        assignment_ids = [assignment_id for _subject, assignment_id, _status in rows]
        worked_assignment_ids = set(
            session.scalars(
                select(ReviewItemAnswer.assignment_id).where(
                    ReviewItemAnswer.tenant_id == tenant_id,
                    ReviewItemAnswer.assignment_id.in_(assignment_ids),
                )
            )
        ) | set(
            session.scalars(
                select(AnnotationRevision.assignment_id).where(
                    AnnotationRevision.tenant_id == tenant_id,
                    AnnotationRevision.assignment_id.in_(assignment_ids),
                )
            )
        )
        has_work_by_case: dict[str, bool] = {}
        for subject, assignment_id, assignment_status in rows:
            case_id = _case_id(subject)
            has_work_by_case[case_id] = has_work_by_case.get(case_id, False) or (
                assignment_id in worked_assignment_ids
                or assignment_status in {"submitted", "revision_requested"}
            )

        submitted_case_ids = set(
            session.scalars(
                select(CaseSubmission.case_id).where(
                    CaseSubmission.tenant_id == tenant_id,
                    CaseSubmission.campaign_id == campaign_id,
                    CaseSubmission.reviewer_id == principal.user.id,
                )
            )
        )
        additions = proposal_counts(session, tenant_id, campaign_id, principal.user.id)
        not_started = in_progress = completed = 0
        for case_id, has_work in has_work_by_case.items():
            if case_id in submitted_case_ids:
                completed += 1
            elif has_work or case_id in additions:
                in_progress += 1
            else:
                not_started += 1
        return {
            "not_started_count": not_started,
            "in_progress_count": in_progress,
            "completed_count": completed,
        }
