"""Private proposal case counts, separate from extracted-field readiness."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.campaign_queries import _minimum_reviews_per_case
from review_platform.review.grouping import classify_unit
from review_platform.review.models import Campaign
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_adjudication_store import match_input, private_items
from review_platform.review.proposal_matching import automatic_proposal_groups
from review_platform.review.proposal_readiness import adjudicable_case_proposals
from review_platform.review.schemas import (
    AdjudicationCampaignCaseItem,
    AdjudicationCampaignFieldProgress,
)

if TYPE_CHECKING:
    from review_platform.review.adjudication_campaign_projections import (
        CaseProjectionRow,
        OrderedAdjudicationCase,
    )


def include_proposal_progress(
    session: Session,
    campaign: Campaign,
    actor: uuid.UUID,
    projections: list[OrderedAdjudicationCase],
    by_case: dict[str, list[CaseProjectionRow]],
) -> None:
    cases_with_proposals = set(
        session.scalars(
            select(ReviewerAddedProposal.case_id)
            .where(
                ReviewerAddedProposal.tenant_id == campaign.tenant_id,
                ReviewerAddedProposal.campaign_id == campaign.id,
                ReviewerAddedProposal.state == "submitted",
            )
            .distinct()
        )
    )
    for projection in projections:
        if projection.item.case_id not in cases_with_proposals:
            continue
        case = projection.item
        rows = by_case[case.case_id]
        groups = {
            classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name).group_id
            for unit, _, _, participation in rows
            if participation and participation.status in {"pending", "submitted"}
        }
        if not groups:
            continue
        proposals = [
            p
            for p in adjudicable_case_proposals(session, campaign=campaign, case_id=case.case_id)
            if p.group_id in groups
        ]
        if not proposals:
            continue
        stored = private_items(session, campaign.tenant_id, campaign.id, case.case_id, actor)
        # Combined targets replace an existing extracted responsibility; count it just once.
        additions = (
            [
                (i.id, i.state == "submitted")
                for i in stored
                if i.state != "superseded" and not i.extracted_adjudication_id
            ]
            if stored
            else [
                (uuid.uuid5(actor, ":".join(str(p.id) for p in group)), False)
                for group in automatic_proposal_groups([match_input(p) for p in proposals])
            ]
        )
        _include_counts(case, additions, _minimum_reviews_per_case(campaign))


def _include_counts(
    case: AdjudicationCampaignCaseItem, additions: list[tuple[uuid.UUID, bool]], required: int
) -> None:
    from review_platform.review.adjudication_campaign_projections import _case_status

    progress = case.progress
    completed = sum(submitted for _, submitted in additions)
    pending = len(additions) - completed
    progress.total_scoped_fields += len(additions)
    progress.personal_responsibility_fields += len(additions)
    progress.completed_responsibility_fields += completed
    progress.submitted_fields += completed
    progress.pending_fields += pending
    case.field_progress.extend(
        AdjudicationCampaignFieldProgress(
            review_unit_id=item_id,
            proposal_item_id=item_id,
            item_label="Reviewer-added item",
            # These are eligible case submissions, not proposal counts or votes.
            submitted_reviews=required,
            required_reviews=required,
            state="adjudicated_by_me" if submitted else "ready_for_adjudication",
        )
        for item_id, submitted in additions
    )
    status, completion, code, reason, anchor, mode = _case_status(
        submitted=progress.submitted_fields,
        waived=progress.waived_fields,
        pending=progress.pending_fields,
        future=progress.future_eligible_fields,
        edit_anchor=case.workspace_adjudication_id,
        view_anchor=case.workspace_adjudication_id,
    )
    case.status, case.completion_kind = status, completion
    case.status_reason_code, case.status_reason = code, reason
    case.workspace_adjudication_id, case.workspace_mode = anchor, mode
