"""Membership-aware protection for existing extracted-field writes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import AdjudicationParticipation
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem


def require_current_membership(
    session: Session,
    participation: AdjudicationParticipation,
    expected: int,
    preferred_proposal_id: uuid.UUID | None = None,
) -> None:
    attached = session.scalar(
        select(ProposalAdjudicationItem.id).where(
            ProposalAdjudicationItem.tenant_id == participation.tenant_id,
            ProposalAdjudicationItem.adjudicator_id == participation.adjudicator_id,
            ProposalAdjudicationItem.extracted_adjudication_id == participation.adjudication_id,
            ProposalAdjudicationItem.state != "superseded",
        )
    )
    if (
        attached
        or participation.membership_version != expected
        or preferred_proposal_id is not None
    ):
        raise APIError(
            412,
            "adjudication_membership_changed",
            "Refresh required",
            "This item's proposal membership changed. Your input has not been saved. "
            "Refresh and reassess the current item before saving or submitting.",
        )


def locked_participation(
    session: Session, tenant: uuid.UUID, actor: uuid.UUID, adjudication_id: uuid.UUID
) -> AdjudicationParticipation:
    participation = session.scalar(
        select(AdjudicationParticipation)
        .where(
            AdjudicationParticipation.tenant_id == tenant,
            AdjudicationParticipation.adjudicator_id == actor,
            AdjudicationParticipation.adjudication_id == adjudication_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if participation is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    if participation.status != "pending":
        raise APIError(
            409,
            "adjudication_not_editable",
            "Item is read-only",
            "Submitted adjudications cannot be edited, combined, or separated.",
        )
    return participation
