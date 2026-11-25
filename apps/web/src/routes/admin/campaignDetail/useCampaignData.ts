import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  getCampaign,
  getCampaignAllocationSummary,
  getCampaignProgress,
  getCampaignScopeCatalog,
  getReviewerWorkload,
  listAllocationRuns,
  listTenantReviewers,
} from "../../../api/admin";

export function useCampaignData({
  tenantId,
  campaignId,
}: {
  tenantId: string;
  campaignId: string;
}) {
  const campaignQuery = useQuery({
    queryKey: ["campaign-detail", tenantId, campaignId],
    queryFn: () => getCampaign(tenantId, campaignId),
    enabled: Boolean(tenantId && campaignId),
  });
  const campaign = campaignQuery.data ?? null;

  const progressQuery = useQuery({
    queryKey: ["admin-campaign-progress", tenantId],
    queryFn: () => getCampaignProgress(tenantId),
    enabled: Boolean(tenantId),
  });
  const progress = useMemo(
    () => progressQuery.data?.items.find((item) => item.campaign_id === campaignId) ?? null,
    [progressQuery.data?.items, campaignId],
  );
  const hasExistingAssignments = (progress?.total_assignments ?? 0) > 0;
  const allocationRunsQuery = useQuery({
    queryKey: ["allocation-runs", tenantId, campaignId],
    queryFn: () => listAllocationRuns(tenantId, campaignId),
    enabled: Boolean(tenantId && campaignId && hasExistingAssignments),
  });
  const basePublishedRun = allocationRunsQuery.data?.items?.find(
    (run) => run.status === "published",
  );

  const rosterQuery = useQuery({
    queryKey: ["admin-reviewers", tenantId],
    queryFn: () => listTenantReviewers(tenantId),
    enabled: Boolean(tenantId),
  });
  const eligibleReviewers = useMemo(
    () => (rosterQuery.data?.items ?? []).filter((reviewer) => reviewer.eligible),
    [rosterQuery.data?.items],
  );
  const reviewerWorkloadQuery = useQuery({
    queryKey: ["campaign-reviewer-workload", tenantId, campaignId],
    queryFn: () => getReviewerWorkload(tenantId, campaignId),
    enabled: Boolean(tenantId && campaignId),
  });

  const scopeCatalogQuery = useQuery({
    queryKey: ["admin-scope-catalog", tenantId],
    queryFn: () => getCampaignScopeCatalog(tenantId),
    enabled: Boolean(tenantId),
    retry: false,
  });
  const scopeGroupLabels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const group of scopeCatalogQuery.data?.groups ?? []) {
      labels.set(group.group_id, group.group_label);
    }
    return labels;
  }, [scopeCatalogQuery.data?.groups]);
  const scopeGroups = useMemo(
    () => [...(scopeCatalogQuery.data?.groups ?? [])].sort((a, b) => a.order - b.order),
    [scopeCatalogQuery.data?.groups],
  );

  const allocationSummaryQuery = useQuery({
    queryKey: ["campaign-allocation-summary", tenantId, campaignId],
    queryFn: () => getCampaignAllocationSummary(tenantId, campaignId),
    enabled: Boolean(tenantId && campaignId),
  });
  const allocationSummary = allocationSummaryQuery.data ?? null;
  return {
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
  };
}
