"""Review-owned persistence models for the synthetic vertical slice.

Grouped by aggregate across submodules; this package re-exports every model so
``from review_platform.review.models import <Model>`` continues to resolve unchanged.
"""

from __future__ import annotations

from review_platform.review.models.allocation_runs import (
    AllocationRun,
    AllocationRunReviewer,
    AllocationRunSubject,
    AssignmentPlan,
    IncrementalMovementPlan,
)
from review_platform.review.models.assignments import (
    Adjudication,
    AdjudicationDecision,
    AdjudicationDraft,
    AdjudicationParticipation,
    AnnotationRevision,
    Assignment,
    CaseSubmission,
    IdempotencyRecord,
    ReviewItemAnswer,
)
from review_platform.review.models.campaigns import (
    Campaign,
    CampaignSubject,
    ReviewerPool,
    ReviewerPoolMember,
)
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.models.snapshots import (
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.review.models.source_render_artifacts import SourceRenderArtifact

__all__ = [
    "ProposalAdjudicationItem",
    "Adjudication",
    "AdjudicationDecision",
    "AdjudicationDraft",
    "AdjudicationParticipation",
    "AllocationRun",
    "AllocationRunReviewer",
    "AllocationRunSubject",
    "AnnotationRevision",
    "Assignment",
    "AssignmentPlan",
    "Campaign",
    "CampaignSubject",
    "Candidate",
    "CaseSubmission",
    "EvidenceWindow",
    "IdempotencyRecord",
    "IncrementalMovementPlan",
    "ReviewItemAnswer",
    "ReviewerAddedProposal",
    "ReviewSubject",
    "ReviewUnit",
    "ReviewerPool",
    "ReviewerPoolMember",
    "SourceRenderArtifact",
    "SourceSnapshot",
]
