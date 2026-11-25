"""Authorized proposal targets for one adjudicator's existing case workspace."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.db.models import User
from review_platform.review.adjudication_workspace import ReviewAdjudicationWorkspaceMixin
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.campaign_queries import _minimum_reviews_per_case
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit, SourceRenderArtifact
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_adjudication_store import (
    initialize_proposal_items,
    lock_proposal_membership,
    match_input,
    private_items,
)
from review_platform.review.proposal_matching import (
    normalized_proposal_value,
    proposal_group_reasons,
)
from review_platform.review.proposal_readiness import (
    adjudicable_case_proposals,
    case_proposals_ready,
)
from review_platform.review.proposal_validation import source_version
from review_platform.review.schemas import AdjudicationCaseWorkspace
from review_platform.review.schemas.proposal_adjudication import (
    AdjudicationProposal,
    ProposalAdjudicationWorkspace,
    ProposalDecision,
    ProposalDecisionItem,
)


def project_proposal_item(
    item: ProposalAdjudicationItem,
    proposals: dict[str, ReviewerAddedProposal],
    users: dict[uuid.UUID, User],
) -> ProposalDecisionItem:
    members = [proposals[pid] for pid in item.proposal_ids_json]
    numbered: dict[uuid.UUID, int] = defaultdict(int)
    views = []
    for proposal in sorted(members, key=lambda p: (str(p.reviewer_id), p.created_at, str(p.id))):
        numbered[proposal.reviewer_id] += 1
        user = users[proposal.reviewer_id]
        views.append(
            AdjudicationProposal.model_validate(
                dict(
                    id=proposal.id,
                    group_id=proposal.group_id,
                    value_schema=proposal.value_schema,
                    original_value=proposal.original_value,
                    value=proposal.value,
                    note=proposal.note,
                    provenance=proposal.provenance_json,
                    state=proposal.state,
                    lock_version=proposal.lock_version,
                    created_at=proposal.created_at,
                    submitted_at=proposal.submitted_at,
                    reviewer_key=user.email_normalized,
                    reviewer_label=user.display_name or user.email_normalized,
                    proposal_number=numbered[proposal.reviewer_id],
                )
            )
        )
    return ProposalDecisionItem.model_validate(
        dict(
            id=item.id,
            group_id=item.group_id,
            extracted_adjudication_id=item.extracted_adjudication_id,
            proposals=views,
            origin=item.origin,
            state=item.state,
            lock_version=item.lock_version,
            matching_reasons=proposal_group_reasons([match_input(p) for p in members]),
            different_values=len({normalized_proposal_value(p.value) for p in members}) > 1,
            reviewer_count=len(numbered),
            draft=ProposalDecision.model_validate(item.draft_json) if item.draft_json else None,
            decision=ProposalDecision.model_validate(item.decision_json)
            if item.decision_json
            else None,
            final_value=item.final_value,
            final_provenance=item.final_provenance_json or [],
            submitted_at=item.submitted_at,
        )
    )


class ReviewProposalAdjudicationReadMixin(ReviewAdjudicationWorkspaceMixin):
    def proposal_adjudication_workspace(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        artifact_store: ArtifactStore | None = None,
    ) -> ProposalAdjudicationWorkspace:
        workspace = self.adjudication_case_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=artifact_store,
        )
        campaign = session.get(Campaign, workspace.campaign.campaign_id)
        if campaign is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        lock_proposal_membership(
            session, tenant_id, campaign.id, workspace.case_id, principal.user.id
        )
        ready = case_proposals_ready(session, campaign=campaign, case_id=workspace.case_id)
        proposals = adjudicable_case_proposals(
            session, campaign=campaign, case_id=workspace.case_id
        )
        groups = {group.group_id for group in workspace.field_groups}
        proposals = [p for p in proposals if p.group_id in groups]
        existing = private_items(
            session, tenant_id, campaign.id, workspace.case_id, principal.user.id
        )
        if ready:
            initialize_proposal_items(session, proposals, principal.user.id, existing)
        items = private_items(session, tenant_id, campaign.id, workspace.case_id, principal.user.id)
        users = {
            u.id: u
            for u in session.scalars(
                select(User).where(User.id.in_({p.reviewer_id for p in proposals}))
            )
        }
        by_id = {str(p.id): p for p in proposals}
        return ProposalAdjudicationWorkspace(
            required_reviews=_minimum_reviews_per_case(campaign),
            ready=ready,
            source_snapshot_id=workspace.source_render.source_snapshot_id,
            source_version=source_version(workspace.source_render.content),
            source_snapshot_ids=matching_source_snapshots(session, tenant_id, workspace),
            items=[
                project_proposal_item(item, by_id, users)
                for item in items
                if item.state != "superseded" and ready
            ],
        )


def matching_source_snapshots(
    session: Session,
    tenant_id: uuid.UUID,
    workspace: AdjudicationCaseWorkspace,
) -> list[uuid.UUID]:
    """Field snapshots may reference the same verified case document artifact.

    Only admit same-campaign/case snapshots whose current source artifact is byte-identical.
    The caller still validates the rendered-text version and each coordinate range.
    """
    anchor = workspace.source_render.source_snapshot_id
    artifact = session.scalar(
        select(SourceRenderArtifact).where(
            SourceRenderArtifact.tenant_id == tenant_id,
            SourceRenderArtifact.source_snapshot_id == anchor,
            SourceRenderArtifact.is_current.is_(True),
        )
    )
    if artifact is None:
        return [anchor]
    snapshots = session.scalars(
        select(ReviewSubject.source_snapshot_id)
        .join(ReviewUnit, ReviewUnit.review_subject_id == ReviewSubject.id)
        .join(
            SourceRenderArtifact,
            SourceRenderArtifact.source_snapshot_id == ReviewSubject.source_snapshot_id,
        )
        .where(
            ReviewSubject.tenant_id == tenant_id,
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == workspace.campaign.campaign_id,
            ReviewSubject.snapshot_local_case_external_id == workspace.case_id,
            SourceRenderArtifact.tenant_id == tenant_id,
            SourceRenderArtifact.is_current.is_(True),
            SourceRenderArtifact.content_digest == artifact.content_digest,
            SourceRenderArtifact.source_system == artifact.source_system,
        )
        .distinct()
    )
    return sorted({anchor, *snapshots}, key=str)
