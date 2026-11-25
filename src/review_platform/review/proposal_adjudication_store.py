"""Adjudicator-private membership persistence, serialized per actor and case."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_matching import ProposalMatchInput, automatic_proposal_groups
from review_platform.review.schemas.proposals import ProposalSpan


def lock_proposal_membership(
    session: Session, tenant: uuid.UUID, campaign: uuid.UUID, case_id: str, actor: uuid.UUID
) -> None:
    key = f"proposal-adjudication:{tenant}:{campaign}:{case_id}:{actor}"
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})


def match_input(proposal: ReviewerAddedProposal) -> ProposalMatchInput:
    return ProposalMatchInput(
        id=proposal.id,
        tenant_id=proposal.tenant_id,
        campaign_id=proposal.campaign_id,
        case_id=proposal.case_id,
        group_id=proposal.group_id,
        value=proposal.value,
        provenance=tuple(ProposalSpan.model_validate(span) for span in proposal.provenance_json),
    )


def private_items(
    session: Session, tenant: uuid.UUID, campaign: uuid.UUID, case_id: str, actor: uuid.UUID
) -> list[ProposalAdjudicationItem]:
    return list(
        session.scalars(
            select(ProposalAdjudicationItem)
            .where(
                ProposalAdjudicationItem.tenant_id == tenant,
                ProposalAdjudicationItem.campaign_id == campaign,
                ProposalAdjudicationItem.case_id == case_id,
                ProposalAdjudicationItem.adjudicator_id == actor,
            )
            .order_by(ProposalAdjudicationItem.created_at, ProposalAdjudicationItem.id)
            .execution_options(populate_existing=True)
        )
    )


def initialize_proposal_items(
    session: Session,
    proposals: list[ReviewerAddedProposal],
    actor: uuid.UUID,
    existing: list[ProposalAdjudicationItem],
) -> None:
    if existing or not proposals:
        return
    for group in automatic_proposal_groups([match_input(p) for p in proposals]):
        proposal = group[0]
        ids = [str(p.id) for p in group]
        session.add(
            ProposalAdjudicationItem(
                id=uuid.uuid5(actor, ":".join(ids)),
                tenant_id=proposal.tenant_id,
                campaign_id=proposal.campaign_id,
                case_id=proposal.case_id,
                group_id=proposal.group_id,
                adjudicator_id=actor,
                proposal_ids_json=ids,
                origin="automatic",
                state="pending",
                lock_version=1,
            )
        )
    session.flush()


def editable_item(
    items: list[ProposalAdjudicationItem], item_id: uuid.UUID, version: int
) -> ProposalAdjudicationItem:
    item = next((item for item in items if item.id == item_id), None)
    if item is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    if item.state == "superseded":
        raise APIError(
            412,
            "adjudication_membership_changed",
            "Refresh required",
            "Membership changed. Refresh and reassess; your input was not saved.",
        )
    if item.state != "pending":
        raise APIError(
            409,
            "proposal_adjudication_locked",
            "Item is read-only",
            "Submitted or replaced adjudication items cannot be changed.",
        )
    if item.lock_version != version:
        raise APIError(
            412, "precondition_failed", "Stale item", "Refresh before changing membership."
        )
    return item
