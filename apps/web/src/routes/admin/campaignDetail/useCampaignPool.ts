import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  applyCampaignCaseFilters,
  applyCampaignCaseIds,
  loadPoolCases,
  previewCampaignAvailability,
} from "../../../api/admin";
import { useDebouncedValue } from "../../../app/useDebouncedValue";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";

export function useCampaignPool({
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
}: {
  loadCaseCountMode: ReturnType<typeof useCampaignControls>["loadCaseCountMode"];
  loadCaseCount: ReturnType<typeof useCampaignControls>["loadCaseCount"];
  campaign: ReturnType<typeof useCampaignData>["campaign"];
  tenantId: string;
  campaignId: string;
  loadFilterState: ReturnType<typeof useCampaignControls>["loadFilterState"];
  allocationSummary: ReturnType<typeof useCampaignData>["allocationSummary"];
  csrfToken: string | null;
  setLoadCasesResult: ReturnType<typeof useCampaignControls>["setLoadCasesResult"];
  setLoadFilterPanelVersion: ReturnType<typeof useCampaignControls>["setLoadFilterPanelVersion"];
  setCasePages: ReturnType<typeof useCampaignControls>["setCasePages"];
  setCaseCursor: ReturnType<typeof useCampaignControls>["setCaseCursor"];
  setCaseHasMore: ReturnType<typeof useCampaignControls>["setCaseHasMore"];
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const loadRequestedCaseCount =
    loadCaseCountMode === "all" ? "all" : Math.max(1, loadCaseCount || 1);
  const loadSourceFamilies = useMemo(
    () => campaign?.review_scope?.source_families ?? [],
    [campaign?.review_scope?.source_families],
  );
  const campaignHasSavedFilter = (campaign?.case_filter?.all?.length ?? 0) > 0;
  const campaignHasSavedCaseIds = Boolean(campaign?.case_id_selection);
  const savedFilterApplyQuery = useQuery({
    queryKey: [
      "campaign-saved-case-filter",
      tenantId,
      campaignId,
      loadSourceFamilies,
      campaign?.case_filter,
    ],
    queryFn: () =>
      applyCampaignCaseFilters(tenantId, {
        source_families: loadSourceFamilies,
        case_filter: campaign?.case_filter ?? { version: "v1", all: [] },
      }),
    enabled: Boolean(tenantId && campaign && campaignHasSavedFilter),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const savedCaseIdApplyQuery = useQuery({
    queryKey: [
      "campaign-saved-case-ids",
      tenantId,
      campaignId,
      loadSourceFamilies,
      campaign?.case_id_selection,
    ],
    queryFn: () =>
      applyCampaignCaseIds(tenantId, {
        source_families: loadSourceFamilies,
        case_id_selection: campaign!.case_id_selection!,
      }),
    enabled: Boolean(tenantId && campaign && campaignHasSavedCaseIds),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const loadFilterReady =
    (!campaignHasSavedFilter || Boolean(savedFilterApplyQuery.data)) &&
    (!campaignHasSavedCaseIds || Boolean(savedCaseIdApplyQuery.data));
  const editFilterReady =
    loadFilterState.ready && loadFilterState.sourceSignature === JSON.stringify(loadSourceFamilies);

  const debouncedLoadCaseCount = useDebouncedValue(loadRequestedCaseCount);
  const loadAvailabilityQuery = useQuery({
    queryKey: [
      "campaign-pool-availability",
      tenantId,
      campaignId,
      campaign?.review_scope,
      debouncedLoadCaseCount,
      savedFilterApplyQuery.data?.applied_filter_token,
      savedCaseIdApplyQuery.data?.applied_case_id_token,
    ],
    queryFn: ({ signal }) =>
      previewCampaignAvailability(
        tenantId,
        {
          source_families: loadSourceFamilies,
          group_ids: campaign?.review_scope?.group_ids ?? [],
          requested_case_count: debouncedLoadCaseCount,
          synthesize_missing_values: campaign?.synthesize_missing_values ?? false,
          ...(campaignHasSavedCaseIds
            ? {
                case_id_selection: campaign?.case_id_selection,
                applied_case_id_token: savedCaseIdApplyQuery.data?.applied_case_id_token,
              }
            : {
                case_filter: campaign?.case_filter,
                applied_filter_token: savedFilterApplyQuery.data?.applied_filter_token,
              }),
        },
        signal,
      ),
    enabled:
      Boolean(tenantId) && Boolean(campaign) && campaign?.status !== "closed" && loadFilterReady,
    placeholderData: (previousData) => previousData,
  });
  const loadAvailability = loadAvailabilityQuery.data;
  const loadNeedsConfirmation =
    loadAvailability?.feasibility === "feasible_with_smaller_count" ||
    loadAvailability?.feasibility === "feasible_with_remaining_fields_only";
  const loadInfeasible =
    loadAvailability?.feasibility === "infeasible_no_cases" ||
    loadAvailability?.feasibility === "infeasible_no_fields";
  const currentCaseCount = allocationSummary?.selected_cases ?? 0;
  const availablePoolCaseCount = loadAvailability?.eligible_cases_count ?? 0;
  const savedFilterSourceCount =
    savedCaseIdApplyQuery.data?.source_pool_cases_count ??
    savedFilterApplyQuery.data?.source_pool_cases_count;
  const savedFilterMatchingCount =
    savedCaseIdApplyQuery.data?.case_id_matching_count ??
    savedFilterApplyQuery.data?.case_filter_matching_count;
  const hasNoFieldGroupRestriction = (campaign?.review_scope?.group_ids?.length ?? 0) === 0;
  const displayedSourcePoolCaseCount =
    loadAvailability?.source_pool_cases_count ?? savedFilterSourceCount ?? null;
  const displayedFilterMatchingCount =
    loadAvailability?.case_filter_matching_count ?? savedFilterMatchingCount ?? null;
  const displayedEligibleCaseCount =
    loadAvailability?.eligible_cases_count ??
    (hasNoFieldGroupRestriction ? (savedFilterMatchingCount ?? null) : null);
  const plannedCasesToAdd =
    loadRequestedCaseCount === "all"
      ? availablePoolCaseCount
      : Math.min(loadRequestedCaseCount, availablePoolCaseCount);
  const displayedProjectedCaseCount =
    displayedEligibleCaseCount === null
      ? null
      : currentCaseCount +
        (loadRequestedCaseCount === "all"
          ? displayedEligibleCaseCount
          : Math.min(loadRequestedCaseCount, displayedEligibleCaseCount));

  // The request count is the number of new pool cases to add. The UI keeps that distinct from the
  // campaign's existing count and shows the projected total before the write.
  const loadCasesMutation = useMutation({
    mutationFn: (confirm: boolean) =>
      loadPoolCases(
        tenantId,
        campaignId,
        {
          requested_case_count: loadRequestedCaseCount,
          synthesize_missing_values: campaign?.synthesize_missing_values ?? false,
          confirm_smaller_count:
            confirm && loadAvailability?.feasibility === "feasible_with_smaller_count",
          confirm_remaining_fields_only:
            confirm && loadAvailability?.feasibility === "feasible_with_remaining_fields_only",
        },
        csrfToken,
      ),
    onSuccess: async (response) => {
      setLoadCasesResult(response);
      setLoadFilterPanelVersion((current) => current + 1);
      setCasePages([]);
      setCaseCursor(null);
      setCaseHasMore(false);

      // Refresh campaign details before recalculating availability for the remaining pool.
      await queryClient.refetchQueries({
        queryKey: ["campaign-detail", tenantId, campaignId],
        exact: true,
        type: "active",
      });
      await Promise.all([
        queryClient.refetchQueries({
          queryKey: ["campaign-allocation-summary", tenantId, campaignId],
          exact: true,
          type: "active",
        }),
        queryClient.refetchQueries({
          queryKey: ["admin-campaign-progress", tenantId],
          exact: true,
          type: "active",
        }),
        queryClient.refetchQueries({
          queryKey: ["campaign-cases", tenantId, campaignId],
          type: "active",
        }),
        queryClient.invalidateQueries({
          queryKey: ["campaign-pool-availability", tenantId, campaignId],
        }),
      ]);
    },
  });
  return {
    editSourceFamilies: loadSourceFamilies,
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
  };
}
