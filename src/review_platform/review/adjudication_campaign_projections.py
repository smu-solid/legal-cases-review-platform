"""Database projection and status arithmetic for adjudication campaign cases."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.review.adjudication_cases import adjudication_case_id
from review_platform.review.adjudication_reviewer_identities import (
    pending_reviewer_identities_by_unit,
)
from review_platform.review.case_display import case_display
from review_platform.review.grouping import display_field_label
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    Assignment,
    Campaign,
    Candidate,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.schemas import (
    AdjudicationCampaignCaseCounts,
    AdjudicationCampaignCaseItem,
    AdjudicationCampaignFieldProgress,
    AdjudicationResponsibilityProgress,
    AdjudicationReviewerIdentity,
)

CaseProjectionRow = tuple[
    ReviewUnit,
    ReviewSubject,
    Adjudication | None,
    AdjudicationParticipation | None,
]


@dataclass(frozen=True)
class OrderedAdjudicationCase:
    item: AdjudicationCampaignCaseItem
    first_created_at: datetime


def adjudication_case_projections(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    adjudicator_id: uuid.UUID,
) -> list[OrderedAdjudicationCase]:
    rows = session.execute(
        select(ReviewUnit, ReviewSubject, Adjudication, AdjudicationParticipation)
        .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
        .outerjoin(Adjudication, Adjudication.review_unit_id == ReviewUnit.id)
        .outerjoin(
            AdjudicationParticipation,
            (AdjudicationParticipation.adjudication_id == Adjudication.id)
            & (AdjudicationParticipation.adjudicator_id == adjudicator_id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id)
        .order_by(ReviewUnit.created_at, ReviewUnit.id)
    ).all()
    review_unit_ids = [row[0].id for row in rows]
    candidates_by_unit = {
        candidate.review_unit_id: candidate
        for candidate in session.scalars(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.review_unit_id.in_(review_unit_ids),
                Candidate.label == "A",
            )
        )
    }
    adjudication_ids = [row[2].id for row in rows if row[2] is not None]
    submitted_review_counts: dict[uuid.UUID, int] = {
        review_unit_id: int(count)
        for review_unit_id, count in session.execute(
            select(Assignment.review_unit_id, func.count(Assignment.id))
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id.in_(review_unit_ids),
                Assignment.status == "submitted",
            )
            .group_by(Assignment.review_unit_id)
        ).all()
    }
    pending_reviewers_by_unit = pending_reviewer_identities_by_unit(
        session, tenant_id=tenant_id, review_unit_ids=review_unit_ids
    )
    adjudications_with_participants = set(
        session.scalars(
            select(AdjudicationParticipation.adjudication_id)
            .where(
                AdjudicationParticipation.tenant_id == tenant_id,
                AdjudicationParticipation.adjudication_id.in_(adjudication_ids),
            )
            .distinct()
        )
    )
    conflicts = set(
        session.scalars(
            select(Assignment.review_unit_id).where(
                Assignment.tenant_id == tenant_id,
                Assignment.reviewer_id == adjudicator_id,
                Assignment.review_unit_id.in_(review_unit_ids),
            )
        )
    )
    by_case: dict[str, list[CaseProjectionRow]] = defaultdict(list)
    for unit, subject, adjudication, participation in rows:
        by_case[adjudication_case_id(subject)].append((unit, subject, adjudication, participation))
    result = [
        _project_case(
            campaign.id,
            case_id,
            case_rows,
            conflicts,
            submitted_review_counts,
            adjudications_with_participants,
            candidates_by_unit,
            pending_reviewers_by_unit,
        )
        for case_id, case_rows in by_case.items()
    ]
    from review_platform.review.proposal_adjudication_progress import include_proposal_progress

    include_proposal_progress(session, campaign, adjudicator_id, result, by_case)
    return sorted(result, key=lambda row: (row.first_created_at, row.item.case_id))


def _project_case(
    campaign_id: uuid.UUID,
    case_id: str,
    rows: list[CaseProjectionRow],
    conflicts: set[uuid.UUID],
    submitted_review_counts: dict[uuid.UUID, int],
    adjudications_with_participants: set[uuid.UUID],
    candidates_by_unit: dict[uuid.UUID, Candidate],
    pending_reviewers_by_unit: dict[uuid.UUID, list[AdjudicationReviewerIdentity]],
) -> OrderedAdjudicationCase:
    submitted = waived = pending = future = not_required = 0
    edit_anchor = view_anchor = None
    for unit, _subject, adjudication, participation in rows:
        if participation is not None and participation.status == "submitted":
            submitted += 1
            view_anchor = (
                view_anchor or adjudication.id if adjudication is not None else view_anchor
            )
        elif participation is not None and participation.status == "waived":
            waived += 1
        elif participation is not None and participation.status == "pending":
            pending += 1
            edit_anchor = (
                edit_anchor or adjudication.id if adjudication is not None else edit_anchor
            )
        elif (
            adjudication is None
            and unit.status in {"pending", "in_review"}
            and unit.id not in conflicts
        ):
            future += 1
        else:
            not_required += 1
    progress = AdjudicationResponsibilityProgress(
        total_scoped_fields=len(rows),
        personal_responsibility_fields=submitted + waived + pending + future,
        completed_responsibility_fields=submitted + waived,
        submitted_fields=submitted,
        waived_fields=waived,
        not_required_fields=not_required,
        pending_fields=pending,
        future_eligible_fields=future,
    )
    field_progress = [
        _project_field_progress(
            unit,
            adjudication,
            participation,
            submitted_review_counts.get(unit.id, 0),
            adjudications_with_participants,
            pending_reviewers_by_unit.get(unit.id, []),
        )
        for unit, _subject, adjudication, participation in rows
    ]
    status, completion, code, reason, anchor, mode = _case_status(
        submitted=submitted,
        waived=waived,
        pending=pending,
        future=future,
        edit_anchor=edit_anchor,
        view_anchor=view_anchor,
    )
    display = case_display(
        ((unit, subject) for unit, subject, _adjudication, _participation in rows),
        candidates_by_unit=candidates_by_unit,
    )
    return OrderedAdjudicationCase(
        item=AdjudicationCampaignCaseItem(
            case_id=case_id,
            campaign_id=campaign_id,
            case_title=display.case_title,
            neutral_citation_display=display.neutral_citation_display,
            reported_citation_display=display.reported_citation_display,
            status=status,
            completion_kind=completion,
            status_reason_code=code,
            status_reason=reason,
            progress=progress,
            field_progress=field_progress,
            workspace_adjudication_id=anchor,
            workspace_mode=mode,
        ),
        first_created_at=min(row[0].created_at for row in rows),
    )


def _case_status(
    *,
    submitted: int,
    waived: int,
    pending: int,
    future: int,
    edit_anchor: uuid.UUID | None,
    view_anchor: uuid.UUID | None,
) -> tuple[
    Literal["waiting", "in_progress", "finished", "not_required"],
    Literal["completed", "not_required", "waived", "completed_with_waiver"] | None,
    str,
    str,
    uuid.UUID | None,
    Literal["edit", "read_only"] | None,
]:
    if pending:
        return (
            "in_progress",
            None,
            "work_available",
            f"{pending} field{'s' if pending != 1 else ''} ready for you",
            edit_anchor,
            "edit",
        )
    if future:
        return (
            "waiting",
            None,
            "awaiting_future_participation",
            "Reviews are still in progress; no new adjudication unit is open",
            None,
            None,
        )
    completion: Literal["completed", "not_required", "waived", "completed_with_waiver"]
    if submitted and waived:
        completion, code = "completed_with_waiver", "completed_with_waiver"
        reason = "Your adjudication responsibility for this case is complete"
    elif submitted:
        completion, code = "completed", "completed_by_me"
        reason = "All adjudication required from you is complete"
    elif waived:
        completion, code = "waived", "participation_waived"
        reason = "Your adjudication participation is no longer active"
    else:
        completion, code = "not_required", "not_required"
        reason = "No adjudication is assigned to you for this case"
    mode: Literal["read_only"] | None
    anchor, mode = (view_anchor, "read_only") if view_anchor is not None else (None, None)
    return (
        "not_required" if completion == "not_required" else "finished",
        completion,
        code,
        reason,
        anchor,
        mode,
    )


def _project_field_progress(
    unit: ReviewUnit,
    adjudication: Adjudication | None,
    participation: AdjudicationParticipation | None,
    submitted_reviews: int,
    adjudications_with_participants: set[uuid.UUID],
    pending_reviewers: list[AdjudicationReviewerIdentity],
) -> AdjudicationCampaignFieldProgress:
    if submitted_reviews < unit.required_reviews:
        state = "awaiting_reviews"
    elif participation is not None and participation.status == "pending":
        state = "ready_for_adjudication"
    elif participation is not None and participation.status == "submitted":
        state = "adjudicated_by_me"
    elif adjudication is not None and adjudication.id not in adjudications_with_participants:
        state = "unavailable"
    else:
        state = "not_assigned_to_me"
    return AdjudicationCampaignFieldProgress(
        review_unit_id=unit.id,
        item_label=display_field_label(unit.field_name, unit.safe_field_label),
        submitted_reviews=submitted_reviews,
        required_reviews=unit.required_reviews,
        state=cast(
            Literal[
                "awaiting_reviews",
                "ready_for_adjudication",
                "adjudicated_by_me",
                "not_assigned_to_me",
                "unavailable",
            ],
            state,
        ),
        pending_reviewers=pending_reviewers if submitted_reviews else [],
    )


def case_counts(rows: list[OrderedAdjudicationCase]) -> AdjudicationCampaignCaseCounts:
    return AdjudicationCampaignCaseCounts(
        all=len(rows),
        waiting=sum(row.item.status == "waiting" for row in rows),
        in_progress=sum(row.item.status == "in_progress" for row in rows),
        finished=sum(row.item.status == "finished" for row in rows),
        not_required=sum(row.item.status == "not_required" for row in rows),
    )
