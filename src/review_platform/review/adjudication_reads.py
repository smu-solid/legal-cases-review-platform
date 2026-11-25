"""Caller-scoped adjudication queue queries and legacy bundle projections.

Authorization and transaction ownership remain with the review service operations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from review_platform.auth.principal import Principal
from review_platform.common.errors import APIError
from review_platform.review.adjudication_cases import adjudication_case_id
from review_platform.review.grouping import display_field_label
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    AnnotationRevision,
    Assignment,
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import (
    candidate_response,
    evidence_response,
    subject_response,
)
from review_platform.review.schemas import (
    AdjudicationBundle,
    AdjudicationFieldProgress,
    AdjudicationSummary,
    CandidateAssessmentInput,
    PseudonymousSubmission,
)

QueueRow = tuple[
    ReviewUnit,
    ReviewSubject,
    Campaign,
    int,
    Adjudication | None,
    AdjudicationParticipation | None,
]


def _queue_snapshot(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    principal: Principal,
) -> tuple[Sequence[Row[QueueRow]], set[uuid.UUID]]:
    submitted_counts = (
        select(
            Assignment.review_unit_id,
            func.count(Assignment.id).label("submitted_reviews"),
        )
        .where(Assignment.tenant_id == tenant_id, Assignment.status == "submitted")
        .group_by(Assignment.review_unit_id)
        .subquery()
    )
    rows = session.execute(
        select(
            ReviewUnit,
            ReviewSubject,
            Campaign,
            func.coalesce(submitted_counts.c.submitted_reviews, 0),
            Adjudication,
            AdjudicationParticipation,
        )
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .join(
            Campaign,
            (Campaign.tenant_id == ReviewUnit.tenant_id) & (Campaign.id == ReviewUnit.campaign_id),
        )
        .outerjoin(
            submitted_counts,
            submitted_counts.c.review_unit_id == ReviewUnit.id,
        )
        .outerjoin(
            Adjudication,
            (Adjudication.tenant_id == ReviewUnit.tenant_id)
            & (Adjudication.review_unit_id == ReviewUnit.id),
        )
        .outerjoin(
            AdjudicationParticipation,
            (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
            & (AdjudicationParticipation.adjudication_id == Adjudication.id)
            & (AdjudicationParticipation.adjudicator_id == principal.user.id),
        )
        .where(
            ReviewUnit.tenant_id == tenant_id,
        )
        .order_by(Campaign.created_at, ReviewUnit.created_at, ReviewUnit.id)
    ).all()
    adjudications_with_participants = set(
        session.scalars(
            select(AdjudicationParticipation.adjudication_id)
            .where(AdjudicationParticipation.tenant_id == tenant_id)
            .distinct()
        )
    )
    return rows, adjudications_with_participants


def adjudication_queue(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    principal: Principal,
) -> list[AdjudicationSummary]:
    rows, adjudications_with_participants = _queue_snapshot(
        session,
        tenant_id=tenant_id,
        principal=principal,
    )
    grouped_rows: dict[tuple[uuid.UUID, str], list[QueueRow]] = {}
    for unit, subject, campaign, submitted, adjudication, participation in rows:
        case_id = adjudication_case_id(subject)
        key = (campaign.id, case_id)
        grouped_rows.setdefault(key, []).append(
            (unit, subject, campaign, int(submitted), adjudication, participation)
        )
    result: list[AdjudicationSummary] = []
    for (campaign_id, case_id), case_rows in grouped_rows.items():
        started = [row for row in case_rows if row[3] > 0]
        if not started:
            continue
        progress: list[AdjudicationFieldProgress] = []
        ready = awaiting = completed = exceptional = submitted_slots = required_slots = 0
        workspace_anchor = None
        for unit, _subject, _campaign, submitted, adjudication, participation in case_rows:
            submitted_slots += submitted
            required_slots += unit.required_reviews
            if 0 < submitted < unit.required_reviews:
                state = "awaiting_reviews"
                awaiting += 1
            elif participation is not None and participation.status == "pending":
                state = "ready_for_me"
                ready += 1
                if adjudication is not None:  # outer-join invariant: participation has a parent
                    workspace_anchor = workspace_anchor or adjudication.id
            elif participation is not None and participation.status == "submitted":
                state = "completed_by_me"
                completed += 1
            elif (
                submitted >= unit.required_reviews
                and adjudication is not None
                and adjudication.id not in adjudications_with_participants
            ):
                state = "unavailable"
                exceptional += 1
            else:
                state = "unavailable"
            progress.append(
                AdjudicationFieldProgress(
                    review_unit_id=unit.id,
                    item_label=display_field_label(unit.field_name, unit.safe_field_label),
                    submitted_reviews=submitted,
                    required_reviews=unit.required_reviews,
                    state=cast(
                        Literal[
                            "ready_for_me",
                            "awaiting_reviews",
                            "completed_by_me",
                            "unavailable",
                        ],
                        state,
                    ),
                )
            )
        if ready == 0 and awaiting == 0 and exceptional == 0:
            continue
        _unit, subject, campaign, *_rest = case_rows[0]
        result.append(
            AdjudicationSummary(
                display_title=subject.display_title,
                case_id=case_id,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                workspace_adjudication_id=workspace_anchor,
                ready_for_me_count=ready,
                awaiting_reviews_count=awaiting,
                completed_by_me_count=completed,
                no_eligible_participant_count=exceptional,
                total_field_count=len(case_rows),
                item_count=ready,
                submitted_review_slots=submitted_slots,
                required_review_slots=required_slots,
                field_progress=progress,
                exceptional_state="no_eligible_participants" if exceptional else None,
            )
        )
    return result


def pending_adjudication(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    adjudication_id: uuid.UUID,
    principal: Principal,
) -> Adjudication:
    adjudication = session.scalar(
        select(Adjudication)
        .join(
            AdjudicationParticipation,
            (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
            & (AdjudicationParticipation.adjudication_id == Adjudication.id),
        )
        .where(
            Adjudication.tenant_id == tenant_id,
            Adjudication.id == adjudication_id,
            Adjudication.status == "pending",
            AdjudicationParticipation.adjudicator_id == principal.user.id,
            AdjudicationParticipation.status == "pending",
        )
    )
    if adjudication is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    conflict = session.scalar(
        select(func.count())
        .select_from(Assignment)
        .where(
            Assignment.tenant_id == tenant_id,
            Assignment.review_unit_id == adjudication.review_unit_id,
            Assignment.reviewer_id == principal.user.id,
        )
    )
    if conflict:  # pragma: no cover - claim eligibility invariant
        raise APIError(403, "adjudication_conflict", "Forbidden", "The action is not permitted.")
    return adjudication


def adjudication_unit(
    session: Session, *, tenant_id: uuid.UUID, adjudication: Adjudication
) -> ReviewUnit:
    unit = session.scalar(
        select(ReviewUnit).where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.id == adjudication.review_unit_id,
        )
    )
    if unit is None:  # pragma: no cover - composite FK invariant
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    return unit


def unit_subject(session: Session, *, tenant_id: uuid.UUID, unit: ReviewUnit) -> ReviewSubject:
    subject = session.scalar(
        select(ReviewSubject).where(
            ReviewSubject.tenant_id == tenant_id,
            ReviewSubject.id == unit.review_subject_id,
        )
    )
    if subject is None:  # pragma: no cover - composite FK invariant
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    return subject


def unit_evidence(
    session: Session, *, tenant_id: uuid.UUID, unit_id: uuid.UUID
) -> list[EvidenceWindow]:
    return list(
        session.scalars(
            select(EvidenceWindow)
            .where(
                EvidenceWindow.tenant_id == tenant_id,
                EvidenceWindow.review_unit_id == unit_id,
            )
            .order_by(EvidenceWindow.ordinal)
        )
    )


def legacy_adjudication_bundle(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    adjudication_id: uuid.UUID,
    principal: Principal,
) -> AdjudicationBundle:
    adjudication = pending_adjudication(
        session,
        tenant_id=tenant_id,
        adjudication_id=adjudication_id,
        principal=principal,
    )
    unit = adjudication_unit(session, tenant_id=tenant_id, adjudication=adjudication)
    subject = unit_subject(session, tenant_id=tenant_id, unit=unit)
    candidates = list(
        session.scalars(
            select(Candidate)
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.review_unit_id == unit.id,
            )
            .order_by(Candidate.label)
        )
    )
    evidence = unit_evidence(session, tenant_id=tenant_id, unit_id=unit.id)
    revisions = list(
        session.scalars(
            select(AnnotationRevision)
            .join(
                Assignment,
                (Assignment.tenant_id == AnnotationRevision.tenant_id)
                & (Assignment.id == AnnotationRevision.assignment_id),
            )
            .where(
                AnnotationRevision.tenant_id == tenant_id,
                Assignment.review_unit_id == unit.id,
                AnnotationRevision.state == "submitted",
            )
            .order_by(AnnotationRevision.created_at, AnnotationRevision.id)
        )
    )
    # Legacy v1 submissions are reconciled from the annotation flow only. Grouped
    # value/provenance submissions are exposed by the additive grouped adjudication bundle.
    submissions = [
        PseudonymousSubmission(
            pseudonym=f"Reviewer {index}",
            outcome=revision.outcome,
            corrected_value=revision.corrected_value_json,
            corrected_value_display=revision.corrected_value_display,
            comment=revision.comment,
            assessments=[
                CandidateAssessmentInput.model_validate(item) for item in revision.assessments_json
            ],
            evidence_ids=[uuid.UUID(value) for value in revision.evidence_ids_json],
            submitted_at=revision.created_at,
        )
        for index, revision in enumerate(revisions, start=1)
    ]
    return AdjudicationBundle(
        adjudication_id=adjudication.id,
        review_subject=subject_response(subject),
        review_kind=unit.review_kind,
        candidates=[candidate_response(candidate) for candidate in candidates],
        evidence_windows=[evidence_response(item, subject.attributes_json) for item in evidence],
        submissions=submissions,
    )
