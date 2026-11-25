"""Transactional review, campaign and adjudication operations."""

from __future__ import annotations

from review_platform.review.adjudication import ReviewAdjudicationMixin
from review_platform.review.adjudication_campaigns import ReviewAdjudicationCampaignMixin
from review_platform.review.adjudication_decisions import ReviewAdjudicationDecisionMixin
from review_platform.review.adjudication_drafts import ReviewAdjudicationDraftMixin
from review_platform.review.adjudication_grouped import ReviewAdjudicationGroupedMixin
from review_platform.review.bundle import ReviewBundleMixin
from review_platform.review.campaign_admin import ReviewAdminMixin
from review_platform.review.campaign_agreement import ReviewCampaignAgreementMixin
from review_platform.review.campaign_cases import ReviewCampaignCasesMixin
from review_platform.review.campaign_lifecycle import ReviewCampaignLifecycleMixin
from review_platform.review.campaign_pool_admin import ReviewCampaignPoolMixin
from review_platform.review.campaign_reviewers import ReviewCampaignReviewersMixin
from review_platform.review.campaign_scope import ReviewCampaignScopeMixin
from review_platform.review.case_submission import ReviewCaseSubmissionMixin
from review_platform.review.claim import ReviewClaimMixin
from review_platform.review.lifecycle import ReviewLifecycleMixin
from review_platform.review.proposal_adjudication_writes import ReviewProposalAdjudicationMixin
from review_platform.review.proposals import ReviewProposalMixin
from review_platform.review.queue import ReviewQueueMixin
from review_platform.review.revision import ReviewRevisionMixin
from review_platform.review.source_render_service import ReviewSourceRenderMixin
from review_platform.review.submissions import ReviewSubmissionMixin
from review_platform.review.synthetic_import import ReviewImportMixin

__all__ = ["ReviewService"]


class ReviewService(
    ReviewImportMixin,
    ReviewQueueMixin,
    ReviewClaimMixin,
    ReviewCaseSubmissionMixin,
    ReviewLifecycleMixin,
    ReviewRevisionMixin,
    ReviewBundleMixin,
    ReviewProposalMixin,
    ReviewSourceRenderMixin,
    ReviewSubmissionMixin,
    ReviewAdminMixin,
    ReviewCampaignAgreementMixin,
    ReviewCampaignCasesMixin,
    ReviewCampaignLifecycleMixin,
    ReviewCampaignPoolMixin,
    ReviewCampaignReviewersMixin,
    ReviewCampaignScopeMixin,
    ReviewAdjudicationCampaignMixin,
    ReviewProposalAdjudicationMixin,
    ReviewAdjudicationGroupedMixin,
    ReviewAdjudicationDecisionMixin,
    ReviewAdjudicationDraftMixin,
    ReviewAdjudicationMixin,
):
    """Reviewer, campaign-manager, and adjudicator review workflow service."""
