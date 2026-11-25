import type { components } from "./generated/openapi";

export type MeResponse = components["schemas"]["MeResponse"];
export type CapabilityFlags = components["schemas"]["CapabilityFlags"];
export type CsrfResponse = components["schemas"]["CsrfResponse"];
export type ReviewQueuePage = components["schemas"]["ReviewQueuePage"];
export type ReviewQueueItem = components["schemas"]["ReviewQueueItem"];
export type ReviewerCampaignQueuePage = components["schemas"]["ReviewerCampaignQueuePage"];
export type ReviewerCampaignSummary = components["schemas"]["ReviewerCampaignSummary"];
export type ReviewerCaseQueuePage = components["schemas"]["ReviewerCaseQueuePage"];
export type ReviewerCaseQueueItem = components["schemas"]["ReviewerCaseQueueItem"];
export type CaseSubmissionResponse = components["schemas"]["CaseSubmissionResponse"];
export type ClaimRequest = components["schemas"]["ClaimRequest"];
export type ClaimResponse = components["schemas"]["ClaimResponse"];
export type ReviewerGroupingBundle = Omit<
  components["schemas"]["ReviewerGroupingBundle"],
  "field_groups"
> & { field_groups: FieldGroup[] };
export type FieldGroup = Omit<components["schemas"]["FieldGroup"], "items"> & {
  items: GroupItem[];
};
// Local workspace projection only; proposals remain separate objects in the API.
export type GroupItem = components["schemas"]["GroupItem"] & {
  reviewer_proposal?: components["schemas"]["ReviewerProposal"];
};
export type ReviewItemAnswerInput = components["schemas"]["ReviewItemAnswerInput"];
export type ReviewItemAnswerResponse = components["schemas"]["ReviewItemAnswerResponse"];
export type CorrectedProvenanceSpan = components["schemas"]["CorrectedProvenanceSpan"];
export type SourceRenderArtifactMetadata = components["schemas"]["SourceRenderArtifactMetadata"];
export type SourceRenderAnchorMap = components["schemas"]["SourceRenderAnchorMap"];
export type ReviewerInviteRequest = components["schemas"]["ReviewerInviteRequest"];
export type ReviewerInviteResponse = components["schemas"]["ReviewerInviteResponse"];
export type TenantReviewerRosterPage = components["schemas"]["TenantReviewerRosterPage"];
export type TenantReviewerRosterItem = components["schemas"]["TenantReviewerRosterItem"];
export type CampaignProgressResponse = components["schemas"]["CampaignProgressResponse"];
export type CampaignProgressItem = components["schemas"]["CampaignProgressItem"];
export type CampaignReviewScopeInput = components["schemas"]["CampaignReviewScopeInput"];
export type CreateCampaignRequest = components["schemas"]["CreateCampaignRequest"];
export type CreateCampaignResponse = components["schemas"]["CreateCampaignResponse"];
export type SyntheticImportRequest = components["schemas"]["SyntheticImportRequest"];
export type SyntheticImportResponse = components["schemas"]["SyntheticImportResponse"];
export type CampaignAvailabilityRequest = components["schemas"]["CampaignAvailabilityRequest"];
export type CampaignAvailabilityResponse = components["schemas"]["CampaignAvailabilityResponse"];
export type CampaignCaseFilter = components["schemas"]["CampaignCaseFilter"];
export type CampaignCaseFilterApplyRequest =
  components["schemas"]["CampaignCaseFilterApplyRequest"];
export type CampaignCaseFilterApplyResponse =
  components["schemas"]["CampaignCaseFilterApplyResponse"];
export type CampaignCaseIdSelection = components["schemas"]["CampaignCaseIdSelection"];
export type CampaignCaseIdApplyRequest = components["schemas"]["CampaignCaseIdApplyRequest"];
export type CampaignCaseIdApplyResponse = components["schemas"]["CampaignCaseIdApplyResponse"];
export type CampaignCaseFilterCorrectionRequest =
  components["schemas"]["CampaignCaseFilterCorrectionRequest"];
export type CampaignCaseFilterCorrectionResponse =
  components["schemas"]["CampaignCaseFilterCorrectionResponse"];
export type CampaignCaseFilterExportRequest =
  components["schemas"]["CampaignCaseFilterExportRequest"];
export type LoadPoolCasesRequest = components["schemas"]["LoadPoolCasesRequest"];
export type LoadPoolCasesResponse = components["schemas"]["LoadPoolCasesResponse"];
export type CampaignScopeCatalogResponse = components["schemas"]["CampaignScopeCatalogResponse"];
export type CampaignDetailResponse = components["schemas"]["CampaignDetailResponse"];
export type CampaignEditRequest = components["schemas"]["CampaignEditRequest"];
export type CampaignDeleteResponse = components["schemas"]["CampaignDeleteResponse"];
export type CampaignAllocationSummaryResponse =
  components["schemas"]["CampaignAllocationSummaryResponse"];
export type CampaignCaseProgressItem = components["schemas"]["CampaignCaseProgressItem"];
export type CampaignCaseProgressPage = components["schemas"]["CampaignCaseProgressPage"];
export type CampaignReviewersResponse = components["schemas"]["CampaignReviewersResponse"];
export type ReviewerWorkloadResponse = components["schemas"]["ReviewerWorkloadResponse"];
export type AllocationPolicyInput = components["schemas"]["AllocationPolicyInput"];
export type AssignmentCounts = components["schemas"]["AssignmentCountsOut"];
export type AllocationPreviewResponse = components["schemas"]["AllocationPreviewResponse"];
export type AllocationRunPage = components["schemas"]["AllocationRunPage"];
export type AllocationPublishResponse = components["schemas"]["AllocationPublishResponse"];
export type IncrementalPolicyInput = components["schemas"]["IncrementalPolicyInput"];
export type IncrementalPreviewResponse = components["schemas"]["IncrementalPreviewResponse"];
export type IncrementalRunResponse = components["schemas"]["IncrementalRunResponse"];
export type IncrementalPublishResponse = components["schemas"]["IncrementalPublishResponse"];
export type AdjudicationSummary = components["schemas"]["AdjudicationSummary"];
export type AdjudicationBundle = components["schemas"]["AdjudicationBundle"];
export type AdjudicationGroupedBundle = components["schemas"]["AdjudicationGroupedBundle"];
export type AdjudicationGroupedItem = components["schemas"]["AdjudicationGroupedItem"];
export type AdjudicationDecisionInput = components["schemas"]["AdjudicationDecisionInput"];
export type AdjudicationDraftInput = components["schemas"]["AdjudicationDraftInput"];
export type AdjudicationDecisionResponse = components["schemas"]["AdjudicationDecisionResponse"];
export type AdjudicationDraftResponse = components["schemas"]["AdjudicationDraftResponse"];
export type AdjudicationCampaignQueuePage = components["schemas"]["AdjudicationCampaignQueuePage"];
export type AdjudicationCampaignCaseQueuePage =
  components["schemas"]["AdjudicationCampaignCaseQueuePage"];
export type AdjudicationCampaignCaseItem = components["schemas"]["AdjudicationCampaignCaseItem"];
export type AdjudicationCaseNeighbors = components["schemas"]["AdjudicationCaseNeighbors"];
type RawAdjudicationWorkspace = components["schemas"]["AdjudicationCaseWorkspace"];
export type AdjudicationCaseWorkspace = Omit<RawAdjudicationWorkspace, "field_groups"> & {
  field_groups: Array<
    Omit<RawAdjudicationWorkspace["field_groups"][number], "items"> & {
      items: AdjudicationWorkspaceItem[];
    }
  >;
};
export type AdjudicationWorkspaceItem = components["schemas"]["AdjudicationWorkspaceItem"] & {
  proposal_item?: components["schemas"]["ProposalDecisionItem"];
  proposal_source?: { snapshotId: string; version: string; snapshotIds?: string[] };
  document_unit_id?: string;
};
