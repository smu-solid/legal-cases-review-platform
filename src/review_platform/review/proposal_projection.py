"""Augment the reviewer bundle with author-only proposals and explicit Add capabilities."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_scope import PROPOSAL_GROUPS, case_submission, own_proposals
from review_platform.review.proposal_validation import source_version
from review_platform.review.schemas.grouped_bundle import ReviewerGroupingBundle
from review_platform.review.schemas.proposals import ReviewerProposal


def proposal_response(proposal: ReviewerAddedProposal) -> ReviewerProposal:
    return ReviewerProposal.model_validate(
        {
            "id": proposal.id,
            "duplicate_acknowledgement": (
                proposal.revisions_json[-1].get("duplicate_acknowledgement")
                if proposal.revisions_json
                else None
            ),
            "group_id": proposal.group_id,
            "value": proposal.value,
            "note": proposal.note,
            "provenance": proposal.provenance_json,
            "original_value": proposal.original_value,
            "value_schema": proposal.value_schema,
            "state": proposal.state,
            "lock_version": proposal.lock_version,
            "created_at": proposal.created_at,
            "submitted_at": proposal.submitted_at,
        }
    )


def attach_proposals(
    bundle: ReviewerGroupingBundle,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    reviewer_id: uuid.UUID,
    campaign_open: bool,
) -> ReviewerGroupingBundle:
    bundle.proposal_source_version = source_version(bundle.source_render.content)
    bundle.case_submitted = (
        case_submission(
            session,
            tenant_id,
            campaign_id,
            case_id,
            reviewer_id,
        )
        is not None
    )
    proposals = own_proposals(session, tenant_id, campaign_id, case_id, reviewer_id)
    allowed = {group.group_id for group in bundle.field_groups}
    bundle.reviewer_additions = [proposal_response(p) for p in proposals if p.group_id in allowed]
    for group in bundle.field_groups:
        if (
            group.group_kind == "non_atomic"
            and group.group_id in PROPOSAL_GROUPS
            and campaign_open
            and not bundle.case_submitted
        ):
            group.add_item_label = PROPOSAL_GROUPS[group.group_id][0]
        additions = [p for p in bundle.reviewer_additions if p.group_id == group.group_id]
        group.item_count += len(additions)
        group.completed_count += sum(p.state == "submitted" for p in additions)
        progress = next(p for p in bundle.progress.group_progress if p.group_id == group.group_id)
        progress.item_count = group.item_count
        progress.completed_count = group.completed_count
    if bundle.case_submitted:
        bundle.allowed_actions = []
    elif campaign_open and any(group.add_item_label for group in bundle.field_groups):
        bundle.allowed_actions = ["save_draft", "submit"]
    bundle.progress.total_items = sum(g.item_count for g in bundle.field_groups)
    bundle.progress.completed_items = sum(g.completed_count for g in bundle.field_groups)
    bundle.progress.remaining_items = bundle.progress.total_items - bundle.progress.completed_items
    return bundle
