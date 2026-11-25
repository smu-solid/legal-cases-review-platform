import { useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import type {
  AllocationPreviewResponse,
  AllocationPublishResponse,
  CampaignCaseProgressItem,
  CampaignDeleteResponse,
  IncrementalPreviewResponse,
  IncrementalPublishResponse,
  LoadPoolCasesResponse,
} from "../../../api/types";
import { hasCapability, useAuthSession } from "../../../auth/authSession";
import { type AppliedCaseSelectionState } from "../CampaignCaseSelectionPanel";
import { useCampaignAllocation } from "./useCampaignAllocation";
import { useCampaignCases } from "./useCampaignCases";
import { useCampaignData } from "./useCampaignData";
import { useCampaignLifecycle } from "./useCampaignLifecycle";
import { useCampaignPool } from "./useCampaignPool";
import { useCampaignReviewers } from "./useCampaignReviewers";
import { useCampaignScopeDraft } from "./useCampaignScopeDraft";

export function useCampaignControls() {
  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [fieldSelectionDraft, setFieldSelectionDraft] = useState<"all" | "selected">("all");
  const [scopeGroupIdsDraft, setScopeGroupIdsDraft] = useState<string[]>([]);
  const [editNeedsConfirm, setEditNeedsConfirm] = useState(false);
  const [deleteRequested, setDeleteRequested] = useState(false);
  const [deleteResult, setDeleteResult] = useState<CampaignDeleteResponse | null>(null);
  const [completeRequested, setCompleteRequested] = useState(false);
  const [previewResult, setPreviewResult] = useState<
    AllocationPreviewResponse | IncrementalPreviewResponse | null
  >(null);
  const [publishResult, setPublishResult] = useState<
    AllocationPublishResponse | IncrementalPublishResponse | null
  >(null);
  const [casePages, setCasePages] = useState<CampaignCaseProgressItem[]>([]);
  const [caseCursor, setCaseCursor] = useState<string | null>(null);
  const [caseHasMore, setCaseHasMore] = useState(false);
  const [loadCaseCountMode, setLoadCaseCountMode] = useState<"all" | "count">("all");
  const [loadCaseCount, setLoadCaseCount] = useState(10);
  const [loadCasesResult, setLoadCasesResult] = useState<LoadPoolCasesResponse | null>(null);
  const [loadFilterPanelVersion, setLoadFilterPanelVersion] = useState(0);
  const [loadFilterState, setLoadFilterState] = useState<AppliedCaseSelectionState>({
    mode: "filter",
    caseFilter: { version: "v1", all: [] },
    filterResult: null,
    caseIdSelection: null,
    caseIdFileName: null,
    caseIdResult: null,
    ready: false,
    sourceSignature: "",
  });
  return {
    editing,
    setEditing,
    nameDraft,
    setNameDraft,
    fieldSelectionDraft,
    setFieldSelectionDraft,
    scopeGroupIdsDraft,
    setScopeGroupIdsDraft,
    editNeedsConfirm,
    setEditNeedsConfirm,
    deleteRequested,
    setDeleteRequested,
    deleteResult,
    setDeleteResult,
    completeRequested,
    setCompleteRequested,
    previewResult,
    setPreviewResult,
    publishResult,
    setPublishResult,
    casePages,
    setCasePages,
    caseCursor,
    setCaseCursor,
    caseHasMore,
    setCaseHasMore,
    loadCaseCountMode,
    setLoadCaseCountMode,
    loadCaseCount,
    setLoadCaseCount,
    loadCasesResult,
    setLoadCasesResult,
    loadFilterPanelVersion,
    setLoadFilterPanelVersion,
    loadFilterState,
    setLoadFilterState,
  };
}

export function useCampaignDetail() {
  const { tenantId = "", campaignId = "" } = useParams();
  const queryClient = useQueryClient();
  const session = useAuthSession();
  const { csrfToken } = session;
  const canManageCampaigns = hasCapability(session, ["can_manage_campaigns"]);
  const {
    editing,
    setEditing,
    nameDraft,
    setNameDraft,
    fieldSelectionDraft,
    setFieldSelectionDraft,
    scopeGroupIdsDraft,
    setScopeGroupIdsDraft,
    editNeedsConfirm,
    setEditNeedsConfirm,
    deleteRequested,
    setDeleteRequested,
    deleteResult,
    setDeleteResult,
    completeRequested,
    setCompleteRequested,
    previewResult,
    setPreviewResult,
    publishResult,
    setPublishResult,
    casePages,
    setCasePages,
    caseCursor,
    setCaseCursor,
    caseHasMore,
    setCaseHasMore,
    loadCaseCountMode,
    setLoadCaseCountMode,
    loadCaseCount,
    setLoadCaseCount,
    loadCasesResult,
    setLoadCasesResult,
    loadFilterPanelVersion,
    setLoadFilterPanelVersion,
    loadFilterState,
    setLoadFilterState,
  } = useCampaignControls();

  const invalidateCampaign = () => {
    void queryClient.invalidateQueries({ queryKey: ["campaign-detail", tenantId, campaignId] });
    void queryClient.invalidateQueries({
      queryKey: ["campaign-allocation-summary", tenantId, campaignId],
    });
    void queryClient.invalidateQueries({ queryKey: ["admin-campaign-progress", tenantId] });
  };
  const {
    campaignQuery,
    campaign,
    progress,
    hasExistingAssignments,
    allocationRunsQuery,
    basePublishedRun,
    rosterQuery,
    eligibleReviewers,
    reviewerWorkloadQuery,
    scopeGroupLabels,
    scopeGroups,
    allocationSummary,
  } = useCampaignData({ tenantId, campaignId });
  const { toggleScopeGroupDraft, reviewScopeDraft, editSelectionChanged } = useCampaignScopeDraft({
    campaign,
    setNameDraft,
    setFieldSelectionDraft,
    setScopeGroupIdsDraft,
    fieldSelectionDraft,
    scopeGroupIdsDraft,
    loadFilterState,
  });

  const { casesQuery } = useCampaignCases({
    setCasePages,
    setCaseCursor,
    setCaseHasMore,
    campaignId,
    tenantId,
    caseCursor,
  });
  const { editMutation, deleteMutation, completeMutation } = useCampaignLifecycle({
    tenantId,
    campaignId,
    nameDraft,
    reviewScopeDraft,
    editSelectionChanged,
    loadFilterState,
    csrfToken,
    queryClient,
    setEditing,
    setEditNeedsConfirm,
    invalidateCampaign,
    setDeleteRequested,
    setDeleteResult,
    setCompleteRequested,
  });

  const {
    editSourceFamilies,
    loadFilterReady,
    editFilterReady,
    loadAvailability,
    loadNeedsConfirmation,
    loadInfeasible,
    currentCaseCount,
    displayedSourcePoolCaseCount,
    displayedFilterMatchingCount,
    displayedEligibleCaseCount,
    plannedCasesToAdd,
    displayedProjectedCaseCount,
    loadCasesMutation,
  } = useCampaignPool({
    loadCaseCountMode,
    loadCaseCount,
    campaign,
    tenantId,
    campaignId,
    loadFilterState,
    allocationSummary,
    csrfToken,
    setLoadCasesResult,
    setLoadFilterPanelVersion,
    setCasePages,
    setCaseCursor,
    setCaseHasMore,
    queryClient,
  });

  const {
    reviewerActionPending,
    reviewerActionError,
    toggleReviewer,
    selectedReviewerIds,
    reviewerHasWork,
    reviewerHasLiveAccess,
    reviewerNameById,
    campaignReviewerRows,
  } = useCampaignReviewers({
    tenantId,
    campaignId,
    csrfToken,
    invalidateCampaign,
    campaign,
    reviewerWorkloadQuery,
    rosterQuery,
  });

  const {
    reviewersLocked,
    campaignCanLoadCases,
    campaignCanEdit,
    campaignCanDelete,
    campaignCanComplete,
    reviewerBoxInvalid,
    allocationBlockedReason,
    allocationPolicy,
    incrementalPolicy,
    previewMutation,
    previewIsPublishable,
    publishMutation,
  } = useCampaignAllocation({
    campaign,
    eligibleReviewers,
    allocationSummary,
    selectedReviewerIds,
    hasExistingAssignments,
    allocationRunsQuery,
    basePublishedRun,
    tenantId,
    campaignId,
    csrfToken,
    setPreviewResult,
    setPublishResult,
    previewResult,
    invalidateCampaign,
    queryClient,
  });

  function handleEditSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    if (editSelectionChanged) {
      setEditNeedsConfirm(true);
      return;
    }
    editMutation.mutate(false);
  }

  function toggleCampaignEditing() {
    if (!campaign) return;
    setNameDraft(campaign.campaign_name);
    const groupIds = campaign.review_scope?.group_ids ?? [];
    setFieldSelectionDraft(groupIds.length > 0 ? "selected" : "all");
    setScopeGroupIdsDraft(groupIds);
    setEditNeedsConfirm(false);
    setLoadFilterPanelVersion((current) => current + 1);
    setEditing((current) => !current);
  }
  return {
    tenantId,
    csrfToken,
    canManageCampaigns,
    editing,
    nameDraft,
    setNameDraft,
    fieldSelectionDraft,
    setFieldSelectionDraft,
    scopeGroupIdsDraft,
    editNeedsConfirm,
    setEditNeedsConfirm,
    deleteRequested,
    setDeleteRequested,
    deleteResult,
    setDeleteResult,
    completeRequested,
    setCompleteRequested,
    previewResult,
    publishResult,
    casePages,
    setCaseCursor,
    caseHasMore,
    loadCaseCountMode,
    setLoadCaseCountMode,
    loadCaseCount,
    setLoadCaseCount,
    loadCasesResult,
    loadFilterPanelVersion,
    setLoadFilterState,
    campaignQuery,
    campaign,
    progress,
    hasExistingAssignments,
    eligibleReviewers,
    scopeGroupLabels,
    scopeGroups,
    allocationSummary,
    toggleScopeGroupDraft,
    casesQuery,
    editMutation,
    deleteMutation,
    completeMutation,
    editSourceFamilies,
    loadFilterReady,
    editFilterReady,
    loadAvailability,
    loadNeedsConfirmation,
    loadInfeasible,
    currentCaseCount,
    displayedSourcePoolCaseCount,
    displayedFilterMatchingCount,
    displayedEligibleCaseCount,
    plannedCasesToAdd,
    displayedProjectedCaseCount,
    loadCasesMutation,
    reviewerActionPending,
    reviewerActionError,
    toggleReviewer,
    selectedReviewerIds,
    reviewerHasWork,
    reviewerHasLiveAccess,
    reviewerNameById,
    campaignReviewerRows,
    reviewersLocked,
    campaignCanLoadCases,
    campaignCanEdit,
    campaignCanDelete,
    campaignCanComplete,
    reviewerBoxInvalid,
    allocationBlockedReason,
    allocationPolicy,
    incrementalPolicy,
    previewMutation,
    previewIsPublishable,
    publishMutation,
    handleEditSubmit,
    toggleCampaignEditing,
  };
}
