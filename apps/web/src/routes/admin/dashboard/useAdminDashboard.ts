import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { hasCapability, useAuthSession } from "../../../auth/authSession";
import { type AppliedCaseSelectionState } from "../CampaignCaseSelectionPanel";
import { generateDefaultCampaignKey, useCampaignAuthoring } from "./useCampaignAuthoring";
import { useDashboardData } from "./useDashboardData";
import { useReviewerInvitation } from "./useReviewerInvitation";

export function useDashboardFormState() {
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteEmailError, setInviteEmailError] = useState<string | null>(null);
  const [campaignKey, setCampaignKey] = useState(generateDefaultCampaignKey);
  const [campaignName, setCampaignName] = useState("Local Pilot");
  const [fieldSelection, setFieldSelection] = useState<"all" | "selected">("all");
  const [selectedScopeGroupIds, setSelectedScopeGroupIds] = useState<string[]>([]);
  const [caseCountMode, setCaseCountMode] = useState<"all" | "count">("all");
  const [caseCount, setCaseCount] = useState(30);
  const minimumReviews = 2;
  const [filterPanelVersion, setFilterPanelVersion] = useState(0);
  // Opt-in: when on, a case missing a selected field group is kept and gets a "missing" review
  // task instead of being excluded, so selecting more fields never shrinks the available cases.
  const [synthesizeMissing, setSynthesizeMissing] = useState(false);
  const [filterState, setFilterState] = useState<AppliedCaseSelectionState>({
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
    inviteEmail,
    setInviteEmail,
    inviteEmailError,
    setInviteEmailError,
    campaignKey,
    setCampaignKey,
    campaignName,
    setCampaignName,
    fieldSelection,
    setFieldSelection,
    selectedScopeGroupIds,
    setSelectedScopeGroupIds,
    caseCountMode,
    setCaseCountMode,
    caseCount,
    setCaseCount,
    minimumReviews,
    filterPanelVersion,
    setFilterPanelVersion,
    synthesizeMissing,
    setSynthesizeMissing,
    filterState,
    setFilterState,
  };
}

export function useAdminDashboard() {
  const { tenantId = "" } = useParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const session = useAuthSession();
  const { csrfToken } = session;
  const canManageCampaigns = hasCapability(session, ["can_manage_campaigns"]);
  const {
    inviteEmail,
    setInviteEmail,
    inviteEmailError,
    setInviteEmailError,
    campaignKey,
    setCampaignKey,
    campaignName,
    setCampaignName,
    fieldSelection,
    setFieldSelection,
    selectedScopeGroupIds,
    setSelectedScopeGroupIds,
    caseCountMode,
    setCaseCountMode,
    caseCount,
    setCaseCount,
    minimumReviews,
    filterPanelVersion,
    setFilterPanelVersion,
    synthesizeMissing,
    setSynthesizeMissing,
    filterState,
    setFilterState,
  } = useDashboardFormState();
  const {
    rosterQuery,
    progressQuery,
    campaigns,
    showClosedCampaigns,
    setShowClosedCampaigns,
    closedCampaignCount,
    visibleCampaigns,
    eligibleReviewers,
    activeReviewers,
    pendingReviewers,
    inactiveReviewers,
    overview,
    scopeGroups,
    scopeGroupLabels,
  } = useDashboardData({ tenantId });
  const { inviteMutation, handleInviteSubmit } = useReviewerInvitation({
    tenantId,
    inviteEmail,
    csrfToken,
    setInviteEmail,
    queryClient,
    setInviteEmailError,
  });
  const {
    canSubmitCampaign,
    caseFilterReady,
    handleCampaignKeyChange,
    handleCampaignNameChange,
    toggleScopeGroup,
    availabilityQuery,
    availability,
    needsConfirmation,
    availabilityInfeasible,
    projectedCampaignCases,
    createCampaignMutation,
    campaignActionPending,
  } = useCampaignAuthoring({
    campaignKey,
    campaignName,
    filterState,
    fieldSelection,
    selectedScopeGroupIds,
    setCampaignKey,
    setCampaignName,
    setFilterPanelVersion,
    setSelectedScopeGroupIds,
    caseCountMode,
    caseCount,
    tenantId,
    synthesizeMissing,
    canManageCampaigns,
    minimumReviews,
    csrfToken,
    queryClient,
    navigate,
  });
  return {
    tenantId,
    csrfToken,
    canManageCampaigns,
    inviteEmail,
    setInviteEmail,
    inviteEmailError,
    setInviteEmailError,
    campaignKey,
    campaignName,
    fieldSelection,
    setFieldSelection,
    selectedScopeGroupIds,
    caseCountMode,
    setCaseCountMode,
    caseCount,
    setCaseCount,
    minimumReviews,
    filterPanelVersion,
    synthesizeMissing,
    setSynthesizeMissing,
    setFilterState,
    rosterQuery,
    progressQuery,
    campaigns,
    showClosedCampaigns,
    setShowClosedCampaigns,
    closedCampaignCount,
    visibleCampaigns,
    eligibleReviewers,
    activeReviewers,
    pendingReviewers,
    inactiveReviewers,
    overview,
    scopeGroups,
    scopeGroupLabels,
    inviteMutation,
    handleInviteSubmit,
    canSubmitCampaign,
    caseFilterReady,
    handleCampaignKeyChange,
    handleCampaignNameChange,
    toggleScopeGroup,
    availabilityQuery,
    availability,
    needsConfirmation,
    availabilityInfeasible,
    projectedCampaignCases,
    createCampaignMutation,
    campaignActionPending,
  };
}
