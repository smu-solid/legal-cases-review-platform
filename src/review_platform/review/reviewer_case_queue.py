"""Reviewer-owned case queue and field progress, including saved additions."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.case_display import case_display
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Candidate,
    CaseSubmission,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.proposal_scope import proposal_counts
from review_platform.review.queue_identity import (
    ReviewerQueueIdentityMixin,
    _case_id,
)
from review_platform.review.schemas import (
    ReviewerCaseQueueItem,
    ReviewerCaseQueuePage,
)


class ReviewerCaseQueueMixin(ReviewerQueueIdentityMixin):
    def case_queue(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ReviewerCaseQueuePage:
        """Case-grouped list of the reviewer's own assignments in one campaign.

        One row per distinct case (grouped by ``snapshot_local_case_external_id``, the same
        identity     the admin per-case table and grouped bundle use -- see
        ``campaign_cases.py`` and     ``grouped_bundle.py``), aggregating every review
        unit/field the reviewer has claimed or     submitted for that case in this
        campaign. Never one row per field: a case with ten claimed     fields is one
        item here, not ten. Covers only the reviewer's own already-claimed/submitted
        work -- the still-open, not-yet-claimed pool stays a flat per-field claim list
        (``queue()``/``listReviewQueue``) since claiming is still a per-field action.
        ``released``     rows are not the reviewer's work (a rebalance moved them
        elsewhere), so a case they are the     only trace of does not appear here at
        all.

        Keyset-paginated by ``(first-claimed-at, case id)`` so a large campaign never
        returns every     case at once. Because grouping is by case, one page's cases
        are chosen first (a distinct-     case keyset query), then only that page's
        assignment rows are aggregated."""

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        allowed_campaign_ids = self._reviewer_campaign_ids(
            session, tenant_id=tenant_id, reviewer_id=principal.user.id
        )
        if campaign_id not in allowed_campaign_ids:
            return ReviewerCaseQueuePage(campaign_id=campaign_id, items=[])

        limit = max(1, min(limit, MAX_PAGE_SIZE))
        case_id_col = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
        first_claimed = func.min(Assignment.claimed_at)
        case_stmt = (
            select(case_id_col.label("case_id"), first_claimed.label("first_claimed"))
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
            .group_by(case_id_col)
            .order_by(first_claimed, case_id_col)
        )
        after = decode_cursor(cursor)
        if after is not None:
            case_stmt = case_stmt.having(
                tuple_(first_claimed, case_id_col)
                > (datetime.fromisoformat(str(after["first_claimed"])), str(after["case_id"]))
            )
        case_page = session.execute(case_stmt.limit(limit + 1)).all()
        has_more = len(case_page) > limit
        case_page = case_page[:limit]
        page_case_ids = [row.case_id for row in case_page]
        if not page_case_ids:
            return ReviewerCaseQueuePage(campaign_id=campaign_id, items=[])
        next_cursor = (
            encode_cursor(
                {
                    "first_claimed": case_page[-1].first_claimed.isoformat(),
                    "case_id": case_page[-1].case_id,
                }
            )
            if has_more
            else None
        )

        rows = session.execute(
            select(Assignment, ReviewUnit, ReviewSubject)
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
                case_id_col.in_(page_case_ids),
                assignment_is_live(),
            )
            .order_by(Assignment.claimed_at, Assignment.id)
        ).all()

        unit_ids = [unit.id for _assignment, unit, _subject in rows]
        candidates_by_unit = {
            candidate.review_unit_id: candidate
            for candidate in session.scalars(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.review_unit_id.in_(unit_ids),
                    Candidate.label == "A",
                )
            )
        }

        submitted_case_ids = set(
            session.scalars(
                select(CaseSubmission.case_id).where(
                    CaseSubmission.tenant_id == tenant_id,
                    CaseSubmission.campaign_id == campaign_id,
                    CaseSubmission.reviewer_id == principal.user.id,
                )
            )
        )
        assignment_ids = [assignment.id for assignment, _unit, _subject in rows]
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

        by_case: dict[str, list[tuple[Assignment, ReviewUnit, ReviewSubject]]] = defaultdict(list)
        for assignment, unit, subject in rows:
            by_case[_case_id(subject)].append((assignment, unit, subject))

        # Emit in the keyset page order (first-claimed, case id) chosen above, so paging is stable.
        additions = proposal_counts(session, tenant_id, campaign_id, principal.user.id)
        items: list[ReviewerCaseQueueItem] = []
        for case_id in page_case_ids:
            case_rows = by_case[case_id]
            display = case_display(
                ((unit, subject) for _assignment, unit, subject in case_rows),
                candidates_by_unit=candidates_by_unit,
            )
            added_total, added_submitted = additions.get(case_id, (0, 0))
            fields_assigned = len(case_rows) + added_total
            fields_submitted = sum(
                1 for assignment, _unit, _subject in case_rows if assignment.status == "submitted"
            )
            fields_submitted += added_submitted
            # "completed" requires the reviewer's own explicit CaseSubmission, not merely that
            # every owned field happens to be individually submitted (see that model's docstring
            # for why campaign-level progress must not derive "case done" from field state alone).
            status: Literal["not_started", "in_progress", "completed"]
            if case_id in submitted_case_ids:
                status = "completed"
            elif added_total or any(
                assignment.id in worked_assignment_ids
                or assignment.status in {"submitted", "revision_requested"}
                for assignment, _unit, _subject in case_rows
            ):
                status = "in_progress"
            else:
                status = "not_started"
            # Anchor on a still-open assignment so opening the case lands on unfinished work; every
            # case here has at least one row, so a fully-submitted case falls back to its first.
            anchor_assignment = next(
                (
                    assignment
                    for assignment, _unit, _subject in case_rows
                    if assignment.status != "submitted"
                ),
                case_rows[0][0],
            )
            items.append(
                ReviewerCaseQueueItem(
                    case_id=case_id,
                    case_title=display.case_title,
                    neutral_citation_display=display.neutral_citation_display,
                    reported_citation_display=display.reported_citation_display,
                    campaign_id=campaign_id,
                    anchor_assignment_id=anchor_assignment.id,
                    fields_assigned=fields_assigned,
                    fields_submitted=fields_submitted,
                    status=status,
                )
            )
        return ReviewerCaseQueuePage(
            campaign_id=campaign_id, items=items, next_cursor=next_cursor, has_more=has_more
        )
