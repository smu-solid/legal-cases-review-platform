import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { listReviewerCampaignQueue, listReviewerCaseQueue } from "../../../api/reviewer";
import { useAuthSession } from "../../../auth/authSession";
import { storedCasePageSize } from "./queueState";
import type { useReviewerQueueState } from "./useReviewerQueue";

export function useAssignedCaseQueue({
  tenantId,
  campaignId,
  session,
  setCasePageSize,
  casePageSize,
  caseRefreshVersion,
  setCurrentPage,
  currentPage,
}: {
  tenantId: string;
  campaignId: string;
  session: ReturnType<typeof useAuthSession>;
  setCasePageSize: ReturnType<typeof useReviewerQueueState>["setCasePageSize"];
  casePageSize: ReturnType<typeof useReviewerQueueState>["casePageSize"];
  caseRefreshVersion: ReturnType<typeof useReviewerQueueState>["caseRefreshVersion"];
  setCurrentPage: ReturnType<typeof useReviewerQueueState>["setCurrentPage"];
  currentPage: ReturnType<typeof useReviewerQueueState>["currentPage"];
}) {
  const campaignsQuery = useQuery({
    queryKey: ["reviewer-campaign-queue", tenantId],
    queryFn: () => listReviewerCampaignQueue(tenantId),
    enabled: Boolean(tenantId),
    retry: false,
  });
  const campaign = campaignsQuery.data?.campaigns?.find((item) => item.campaign_id === campaignId);

  useEffect(() => {
    if (session.me?.id) {
      setCasePageSize(storedCasePageSize(session.me.id));
    }
  }, [session.me?.id, setCasePageSize]);

  const casesQuery = useInfiniteQuery({
    queryKey: ["reviewer-case-queue", tenantId, campaignId, casePageSize, caseRefreshVersion],
    queryFn: ({ pageParam }) =>
      listReviewerCaseQueue(tenantId, campaignId, { cursor: pageParam, limit: casePageSize }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
    enabled: Boolean(tenantId && campaignId),
    retry: false,
  });

  // A new page size or a manual refresh rebuilds the keyset query from page 0, so snap back there.
  useEffect(() => {
    setCurrentPage(0);
  }, [casePageSize, caseRefreshVersion, setCurrentPage]);

  const loadedCasePages = casesQuery.data?.pages ?? [];
  // Auto-fetch forward when the reviewer jumps to a page not yet loaded (keyset only exposes the
  // next cursor, so pages must be materialized in order).
  useEffect(() => {
    if (
      currentPage >= loadedCasePages.length &&
      casesQuery.hasNextPage &&
      !casesQuery.isFetchingNextPage
    ) {
      void casesQuery.fetchNextPage();
    }
  }, [
    currentPage,
    loadedCasePages.length,
    casesQuery.hasNextPage,
    casesQuery.isFetchingNextPage,
    casesQuery,
  ]);
  return { campaignsQuery, campaign, casesQuery, loadedCasePages };
}
export function useAssignedCasePagination({
  casesQuery,
  campaign,
  casePageSize,
  loadedCasePages,
  currentPage,
  renderedAssignedTotalRef,
  lastNotifiedTotalRef,
  tenantId,
  campaignId,
  setNewCasesNotice,
}: {
  casesQuery: ReturnType<typeof useAssignedCaseQueue>["casesQuery"];
  campaign: ReturnType<typeof useAssignedCaseQueue>["campaign"];
  casePageSize: ReturnType<typeof useReviewerQueueState>["casePageSize"];
  loadedCasePages: ReturnType<typeof useAssignedCaseQueue>["loadedCasePages"];
  currentPage: ReturnType<typeof useReviewerQueueState>["currentPage"];
  renderedAssignedTotalRef: ReturnType<typeof useReviewerQueueState>["renderedAssignedTotalRef"];
  lastNotifiedTotalRef: ReturnType<typeof useReviewerQueueState>["lastNotifiedTotalRef"];
  tenantId: string;
  campaignId: string;
  setNewCasesNotice: ReturnType<typeof useReviewerQueueState>["setNewCasesNotice"];
}) {
  const cases = casesQuery.data?.pages.flatMap((page) => page.items ?? []) ?? [];
  // The case-queue pages carry no total (keyset pagination exposes only has_more/next_cursor), but
  // the campaign summary's own-work counts sum to exactly this reviewer's assigned-case total, so
  // the heading can show "(N)" without a backend change. Omitted while the summary hasn't loaded.
  const assignedCaseTotal = campaign
    ? campaign.not_started_count + campaign.in_progress_count + campaign.completed_count
    : null;
  // Total pages come from the reviewer's assigned-case total (from the campaign summary) when known;
  // otherwise fall back to what keyset pagination has revealed so far.
  const totalCasePages =
    assignedCaseTotal !== null && casePageSize > 0
      ? Math.max(1, Math.ceil(assignedCaseTotal / casePageSize))
      : Math.max(1, loadedCasePages.length + (casesQuery.hasNextPage ? 1 : 0));
  const pageCases = loadedCasePages[currentPage]?.items ?? [];
  const isPageLoading =
    currentPage >= loadedCasePages.length &&
    (casesQuery.isFetchingNextPage || casesQuery.isLoading);
  const pageRangeStart = assignedCaseTotal === 0 ? 0 : currentPage * casePageSize + 1;
  const pageRangeEnd =
    assignedCaseTotal !== null
      ? Math.min(assignedCaseTotal, currentPage * casePageSize + pageCases.length)
      : currentPage * casePageSize + pageCases.length;
  useEffect(() => {
    if (assignedCaseTotal !== null && renderedAssignedTotalRef.current === null) {
      renderedAssignedTotalRef.current = assignedCaseTotal;
      lastNotifiedTotalRef.current = assignedCaseTotal;
    }
  }, [assignedCaseTotal, lastNotifiedTotalRef, renderedAssignedTotalRef]);

  useEffect(() => {
    let active = true;
    const checkForNewCases = async () => {
      if (!tenantId || !campaignId) {
        return;
      }
      try {
        const latest = await listReviewerCampaignQueue(tenantId);
        if (!active) {
          return;
        }
        const latestCampaign = latest.campaigns.find((item) => item.campaign_id === campaignId);
        if (!latestCampaign) {
          return;
        }
        const latestTotal =
          latestCampaign.not_started_count +
          latestCampaign.in_progress_count +
          latestCampaign.completed_count;
        const renderedTotal = renderedAssignedTotalRef.current;
        const lastNotified = lastNotifiedTotalRef.current ?? renderedTotal;
        if (
          renderedTotal !== null &&
          latestTotal > renderedTotal &&
          (lastNotified === null || latestTotal > lastNotified)
        ) {
          lastNotifiedTotalRef.current = latestTotal;
          setNewCasesNotice({ count: latestTotal - renderedTotal, latestTotal });
        }
      } catch {
        // This background check is advisory. The visible queue and its normal error handling stay
        // untouched when a focus-time request fails.
      }
    };
    window.addEventListener("focus", checkForNewCases);
    return () => {
      active = false;
      window.removeEventListener("focus", checkForNewCases);
    };
  }, [campaignId, lastNotifiedTotalRef, renderedAssignedTotalRef, setNewCasesNotice, tenantId]);
  return {
    cases,
    assignedCaseTotal,
    totalCasePages,
    pageCases,
    isPageLoading,
    pageRangeStart,
    pageRangeEnd,
  };
}
