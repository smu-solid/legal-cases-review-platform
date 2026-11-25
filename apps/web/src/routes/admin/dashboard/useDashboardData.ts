import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  getCampaignProgress,
  getCampaignScopeCatalog,
  listTenantReviewers,
} from "../../../api/admin";

export function useDashboardData({ tenantId }: { tenantId: string }) {
  const rosterQuery = useQuery({
    queryKey: ["admin-reviewers", tenantId],
    queryFn: () => listTenantReviewers(tenantId),
    enabled: Boolean(tenantId),
  });

  const progressQuery = useQuery({
    queryKey: ["admin-campaign-progress", tenantId],
    queryFn: () => getCampaignProgress(tenantId),
    enabled: Boolean(tenantId),
  });

  const scopeCatalogQuery = useQuery({
    queryKey: ["admin-scope-catalog", tenantId],
    queryFn: () => getCampaignScopeCatalog(tenantId),
    enabled: Boolean(tenantId),
    // Capability-gated; a non-campaign_manager admin may receive 403. Do not retry
    // so a forbidden role fails once into the quiet deferred state instead of looping.
    retry: false,
  });

  const campaigns = useMemo(() => progressQuery.data?.items ?? [], [progressQuery.data?.items]);
  const [showClosedCampaigns, setShowClosedCampaigns] = useState(false);
  const closedCampaignCount = useMemo(
    () => campaigns.filter((campaign) => campaign.campaign_status === "closed").length,
    [campaigns],
  );
  const visibleCampaigns = useMemo(
    () =>
      showClosedCampaigns
        ? campaigns
        : campaigns.filter((campaign) => campaign.campaign_status !== "closed"),
    [campaigns, showClosedCampaigns],
  );
  const reviewers = useMemo(() => rosterQuery.data?.items ?? [], [rosterQuery.data?.items]);
  const eligibleReviewers = useMemo(
    () => reviewers.filter((reviewer) => reviewer.eligible),
    [reviewers],
  );
  // Group by the backend's own roster_status label; never infer status client-side.
  const activeReviewers = useMemo(
    () => reviewers.filter((reviewer) => reviewer.roster_status === "active"),
    [reviewers],
  );
  const pendingReviewers = useMemo(
    () => reviewers.filter((reviewer) => reviewer.roster_status === "pending"),
    [reviewers],
  );
  const inactiveReviewers = useMemo(
    () =>
      reviewers.filter(
        (reviewer) =>
          reviewer.roster_status === "disabled" || reviewer.roster_status === "ineligible",
      ),
    [reviewers],
  );
  // Tenant overview aggregated from the backend campaign-progress counts. No client-side
  // fabrication: every number is a sum of real per-campaign counts, or 0 when no campaign exists.
  const overview = useMemo(() => {
    return campaigns.reduce(
      (acc, campaign) => {
        acc.totalCases += campaign.cases_total;
        acc.totalUnits += campaign.total_units;
        acc.pending += campaign.unit_status_counts.pending;
        acc.inReview += campaign.unit_status_counts.in_review;
        acc.inAdjudication += campaign.unit_status_counts.in_adjudication;
        acc.completed += campaign.unit_status_counts.resolved;
        acc.totalAssignments += campaign.total_assignments;
        acc.claimed += campaign.assignment_status_counts.claimed;
        acc.submitted += campaign.assignment_status_counts.submitted;
        return acc;
      },
      {
        totalCases: 0,
        totalUnits: 0,
        pending: 0,
        inReview: 0,
        inAdjudication: 0,
        completed: 0,
        totalAssignments: 0,
        claimed: 0,
        submitted: 0,
      },
    );
  }, [campaigns]);
  const scopeGroups = useMemo(
    () => [...(scopeCatalogQuery.data?.groups ?? [])].sort((a, b) => a.order - b.order),
    [scopeCatalogQuery.data?.groups],
  );
  const scopeGroupLabels = useMemo(
    () => new Map(scopeGroups.map((group) => [group.group_id, group.group_label])),
    [scopeGroups],
  );
  return {
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
  };
}
