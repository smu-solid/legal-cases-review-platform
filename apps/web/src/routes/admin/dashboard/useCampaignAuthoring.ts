import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { createCampaign, previewCampaignAvailability } from "../../../api/admin";
import type { CampaignReviewScopeInput } from "../../../api/types";
import { useDebouncedValue } from "../../../app/useDebouncedValue";
import type { useDashboardFormState } from "./useAdminDashboard";

export function generateDefaultCampaignKey() {
  return `local-pilot-${crypto.randomUUID().slice(0, 8)}`;
}

export function useCampaignAuthoring({
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
}: {
  campaignKey: ReturnType<typeof useDashboardFormState>["campaignKey"];
  campaignName: ReturnType<typeof useDashboardFormState>["campaignName"];
  filterState: ReturnType<typeof useDashboardFormState>["filterState"];
  fieldSelection: ReturnType<typeof useDashboardFormState>["fieldSelection"];
  selectedScopeGroupIds: ReturnType<typeof useDashboardFormState>["selectedScopeGroupIds"];
  setCampaignKey: ReturnType<typeof useDashboardFormState>["setCampaignKey"];
  setCampaignName: ReturnType<typeof useDashboardFormState>["setCampaignName"];
  setFilterPanelVersion: ReturnType<typeof useDashboardFormState>["setFilterPanelVersion"];
  setSelectedScopeGroupIds: ReturnType<typeof useDashboardFormState>["setSelectedScopeGroupIds"];
  caseCountMode: ReturnType<typeof useDashboardFormState>["caseCountMode"];
  caseCount: ReturnType<typeof useDashboardFormState>["caseCount"];
  tenantId: string;
  synthesizeMissing: ReturnType<typeof useDashboardFormState>["synthesizeMissing"];
  canManageCampaigns: boolean;
  minimumReviews: ReturnType<typeof useDashboardFormState>["minimumReviews"];
  csrfToken: string | null;
  queryClient: ReturnType<typeof useQueryClient>;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const trimmedCampaignKey = campaignKey.trim();
  const trimmedCampaignName = campaignName.trim();
  const canSubmitCampaign = trimmedCampaignKey.length > 0 && trimmedCampaignName.length > 0;
  const caseFilterReady = filterState.ready;
  const campaignReviewScope = useMemo<CampaignReviewScopeInput | undefined>(() => {
    const groupIds = fieldSelection === "all" ? [] : selectedScopeGroupIds;
    if (groupIds.length === 0) {
      return undefined;
    }
    return { group_ids: groupIds };
  }, [fieldSelection, selectedScopeGroupIds]);

  function onCampaignAuthored() {
    setCampaignKey(generateDefaultCampaignKey());
    setCampaignName("Local Pilot");
    setFilterPanelVersion((current) => current + 1);
  }

  function handleCampaignKeyChange(value: string) {
    setCampaignKey(value);
    createCampaignMutation.reset();
  }

  function handleCampaignNameChange(value: string) {
    setCampaignName(value);
    createCampaignMutation.reset();
  }

  function toggleScopeGroup(groupId: string) {
    setSelectedScopeGroupIds((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  }

  const requestedCaseCount = caseCountMode === "all" ? "all" : Math.max(1, caseCount || 1);

  const debouncedScopeGroupIds = useDebouncedValue(selectedScopeGroupIds);
  const debouncedCaseCount = useDebouncedValue(requestedCaseCount);
  const availabilityQuery = useQuery({
    queryKey: [
      "admin-campaign-availability",
      tenantId,
      fieldSelection,
      debouncedScopeGroupIds,
      debouncedCaseCount,
      synthesizeMissing,
      filterState.mode,
      filterState.filterResult?.applied_filter_token,
      filterState.caseIdResult?.applied_case_id_token,
    ],
    queryFn: ({ signal }) =>
      previewCampaignAvailability(
        tenantId,
        {
          group_ids: fieldSelection === "all" ? [] : debouncedScopeGroupIds,
          requested_case_count: debouncedCaseCount,
          synthesize_missing_values: synthesizeMissing,
          ...(filterState.mode === "filter"
            ? {
                case_filter: filterState.caseFilter,
                applied_filter_token: filterState.filterResult?.applied_filter_token,
              }
            : {
                case_id_selection: filterState.caseIdSelection,
                applied_case_id_token: filterState.caseIdResult?.applied_case_id_token,
              }),
        },
        signal,
      ),
    enabled: Boolean(tenantId) && canManageCampaigns && caseFilterReady,
    placeholderData: (previousData) => previousData,
  });
  const availability = availabilityQuery.data;
  const needsConfirmation =
    availability?.feasibility === "feasible_with_smaller_count" ||
    availability?.feasibility === "feasible_with_remaining_fields_only";
  const availabilityInfeasible =
    availability?.feasibility === "infeasible_no_cases" ||
    availability?.feasibility === "infeasible_no_fields";
  const projectedCampaignCases = availability?.projected_campaign_cases_count ?? 0;

  const createCampaignMutation = useMutation({
    mutationFn: (confirm: boolean) =>
      createCampaign(
        tenantId,
        {
          campaign_key: trimmedCampaignKey,
          campaign_name: trimmedCampaignName,
          reviews_per_case: minimumReviews,
          review_scope: campaignReviewScope ?? null,
          requested_case_count: requestedCaseCount,
          synthesize_missing_values: synthesizeMissing,
          ...(filterState.mode === "filter"
            ? {
                case_filter: filterState.caseFilter,
                applied_filter_token: filterState.filterResult?.applied_filter_token,
              }
            : {
                case_id_selection: filterState.caseIdSelection,
                applied_case_id_token: filterState.caseIdResult?.applied_case_id_token,
                case_id_selection_file_name: filterState.caseIdFileName,
              }),
          confirm_smaller_count:
            confirm && availability?.feasibility === "feasible_with_smaller_count",
          confirm_remaining_fields_only:
            confirm && availability?.feasibility === "feasible_with_remaining_fields_only",
        },
        csrfToken,
      ),
    onSuccess: (response) => {
      // Refresh the list before navigating to the newly authored campaign.
      void queryClient.invalidateQueries({ queryKey: ["admin-campaign-progress", tenantId] });
      if (!response.not_ready_for_publish) {
        onCampaignAuthored();
        navigate(`/t/${tenantId}/admin/campaigns/${response.campaign_id}`);
      }
    },
  });

  const campaignActionPending = createCampaignMutation.isPending;
  return {
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
