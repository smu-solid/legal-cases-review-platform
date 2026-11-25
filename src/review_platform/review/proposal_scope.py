"""Case serialization and reviewer-owned proposal queries shared by read/write paths."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import CaseSubmission
from review_platform.review.models.proposals import ReviewerAddedProposal

# Explicit authored-value contracts. Directed/structured relations are intentionally unsupported.
PROPOSAL_GROUPS = {
    "cited_cases": ("cited case", "cited_case_text/v1"),
    "statutes_cited": ("statute reference", "statute_reference_text/v1"),
}


def lock_reviewer_case(
    session: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    reviewer_id: uuid.UUID,
) -> None:
    scope = f"reviewer-case:{tenant_id}:{campaign_id}:{case_id}:{reviewer_id}"
    lock_id = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})


def case_submission(
    session: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    reviewer_id: uuid.UUID,
) -> CaseSubmission | None:
    return session.scalar(
        select(CaseSubmission).where(
            CaseSubmission.tenant_id == tenant_id,
            CaseSubmission.campaign_id == campaign_id,
            CaseSubmission.case_id == case_id,
            CaseSubmission.reviewer_id == reviewer_id,
        )
    )


def own_proposals(
    session: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    reviewer_id: uuid.UUID,
) -> list[ReviewerAddedProposal]:
    return list(
        session.scalars(
            select(ReviewerAddedProposal)
            .where(
                ReviewerAddedProposal.tenant_id == tenant_id,
                ReviewerAddedProposal.campaign_id == campaign_id,
                ReviewerAddedProposal.case_id == case_id,
                ReviewerAddedProposal.reviewer_id == reviewer_id,
                ReviewerAddedProposal.state != "removed",
            )
            .order_by(ReviewerAddedProposal.created_at, ReviewerAddedProposal.id)
        )
    )


def require_completed_proposals(
    session: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    reviewer_id: uuid.UUID,
) -> None:
    if any(
        p.state != "submitted"
        for p in own_proposals(
            session,
            tenant_id,
            campaign_id,
            case_id,
            reviewer_id,
        )
    ):
        raise APIError(
            422,
            "case_not_fully_submitted",
            "Incomplete additions",
            "Complete or remove every reviewer-added item before submitting this case.",
        )


def proposal_counts(
    session: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    reviewer_id: uuid.UUID,
) -> dict[str, tuple[int, int]]:
    rows = session.execute(
        select(
            ReviewerAddedProposal.case_id,
            ReviewerAddedProposal.state,
        ).where(
            ReviewerAddedProposal.tenant_id == tenant_id,
            ReviewerAddedProposal.campaign_id == campaign_id,
            ReviewerAddedProposal.reviewer_id == reviewer_id,
            ReviewerAddedProposal.state != "removed",
        )
    ).all()
    counts: dict[str, tuple[int, int]] = {}
    for case_id, state in rows:
        total, submitted = counts.get(case_id, (0, 0))
        counts[case_id] = (total + 1, submitted + int(state == "submitted"))
    return counts


def eligible_proposal_query() -> Select[tuple[ReviewerAddedProposal]]:
    """Select proposals whose author submitted the case; callers apply authorization and scope."""
    return (
        select(ReviewerAddedProposal)
        .join(
            CaseSubmission,
            (
                (CaseSubmission.tenant_id == ReviewerAddedProposal.tenant_id)
                & (CaseSubmission.campaign_id == ReviewerAddedProposal.campaign_id)
                & (CaseSubmission.case_id == ReviewerAddedProposal.case_id)
                & (CaseSubmission.reviewer_id == ReviewerAddedProposal.reviewer_id)
            ),
        )
        .where(ReviewerAddedProposal.state == "submitted")
    )


def campaign_has_proposals(session: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(ReviewerAddedProposal.id)
            .where(
                ReviewerAddedProposal.tenant_id == tenant_id,
                ReviewerAddedProposal.campaign_id == campaign_id,
                ReviewerAddedProposal.state != "removed",
            )
            .limit(1)
        )
        is not None
    )
