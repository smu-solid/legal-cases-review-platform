"""Case-submission gate for reviewer additions, separate from field-review readiness."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.campaign_queries import _minimum_reviews_per_case
from review_platform.review.models import (
    Assignment,
    Campaign,
    CaseSubmission,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_scope import eligible_proposal_query


def submitted_case_reviewers(
    session: Session, *, campaign: Campaign, case_id: str
) -> set[uuid.UUID]:
    """Count durable case confirmations from reviewers assigned this case, once per author.

    Submitted assignments remain valid historical participation when the campaign roster changes.
    Released assignments alone cannot establish eligibility. Individual field submission cannot
    substitute for a CaseSubmission record.
    """
    assigned = (
        select(Assignment.id)
        .join(ReviewUnit, ReviewUnit.id == Assignment.review_unit_id)
        .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
        .where(
            Assignment.tenant_id == campaign.tenant_id,
            ReviewUnit.tenant_id == campaign.tenant_id,
            ReviewSubject.tenant_id == campaign.tenant_id,
            ReviewUnit.campaign_id == campaign.id,
            ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext == case_id,
            Assignment.reviewer_id == CaseSubmission.reviewer_id,
            Assignment.status == "submitted",
        )
        .exists()
    )
    return set(
        session.scalars(
            select(CaseSubmission.reviewer_id).where(
                CaseSubmission.tenant_id == campaign.tenant_id,
                CaseSubmission.campaign_id == campaign.id,
                CaseSubmission.case_id == case_id,
                assigned,
            )
        )
    )


def case_proposals_ready(session: Session, *, campaign: Campaign, case_id: str) -> bool:
    return len(submitted_case_reviewers(session, campaign=campaign, case_id=case_id)) >= (
        _minimum_reviews_per_case(campaign)
    )


def adjudicable_case_proposals(
    session: Session, *, campaign: Campaign, case_id: str
) -> list[ReviewerAddedProposal]:
    """Internal read helper; caller must authorize adjudication access before calling."""
    reviewers = submitted_case_reviewers(session, campaign=campaign, case_id=case_id)
    if len(reviewers) < _minimum_reviews_per_case(campaign):
        return []
    return list(
        session.scalars(
            eligible_proposal_query()
            .where(
                ReviewerAddedProposal.tenant_id == campaign.tenant_id,
                ReviewerAddedProposal.campaign_id == campaign.id,
                ReviewerAddedProposal.case_id == case_id,
                ReviewerAddedProposal.reviewer_id.in_(reviewers),
            )
            .order_by(ReviewerAddedProposal.id)
        )
    )
