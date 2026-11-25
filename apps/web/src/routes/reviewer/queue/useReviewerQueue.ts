import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuthSession } from "../../../auth/authSession";
import { useCaseSubmitToast } from "../useCaseSubmitToast";
import { DEFAULT_CASE_PAGE_SIZE, groupAvailableByCase } from "./queueState";
import { useAssignedCasePagination, useAssignedCaseQueue } from "./useAssignedCaseQueue";
import { useAvailableCaseQueue } from "./useAvailableCaseQueue";
import { useCaseClaimActions } from "./useCaseClaimActions";

export function useReviewerQueueState({ session }: { session: ReturnType<typeof useAuthSession> }) {
  const [claimingCaseId, setClaimingCaseId] = useState<string | null>(null);
  const [caseClaimErrors, setCaseClaimErrors] = useState<Record<string, string>>({});
  const reviewerId = session.me?.id ?? "unknown";
  const [casePageSize, setCasePageSize] = useState(DEFAULT_CASE_PAGE_SIZE);
  const [caseRefreshVersion, setCaseRefreshVersion] = useState(0);
  // 0-based index of the page currently shown. The queue is keyset-paginated, so page N is only
  // reachable once pages 0..N have been fetched; an effect below fetches forward when the reviewer
  // jumps ahead. Reset whenever the underlying query is rebuilt (page size / manual refresh).
  const [currentPage, setCurrentPage] = useState(0);
  const [newCasesNotice, setNewCasesNotice] = useState<{
    count: number;
    latestTotal: number;
  } | null>(null);
  const renderedAssignedTotalRef = useRef<number | null>(null);
  const lastNotifiedTotalRef = useRef<number | null>(null);
  // Brief success banner surfaced when a final case submit auto-navigated the reviewer here because
  // it was the last assigned case in the campaign (see ReviewerWorkspacePage's confirmCaseSubmit).
  const caseSubmitToast = useCaseSubmitToast();
  return {
    claimingCaseId,
    setClaimingCaseId,
    caseClaimErrors,
    setCaseClaimErrors,
    reviewerId,
    casePageSize,
    setCasePageSize,
    caseRefreshVersion,
    setCaseRefreshVersion,
    currentPage,
    setCurrentPage,
    newCasesNotice,
    setNewCasesNotice,
    renderedAssignedTotalRef,
    lastNotifiedTotalRef,
    caseSubmitToast,
  };
}

export function useReviewerQueue() {
  const { tenantId = "", campaignId = "" } = useParams();
  const navigate = useNavigate();
  const session = useAuthSession();
  const queryClient = useQueryClient();
  const {
    claimingCaseId,
    setClaimingCaseId,
    caseClaimErrors,
    setCaseClaimErrors,
    reviewerId,
    casePageSize,
    setCasePageSize,
    caseRefreshVersion,
    setCaseRefreshVersion,
    currentPage,
    setCurrentPage,
    newCasesNotice,
    setNewCasesNotice,
    renderedAssignedTotalRef,
    lastNotifiedTotalRef,
    caseSubmitToast,
  } = useReviewerQueueState({ session });
  const { campaignsQuery, campaign, casesQuery, loadedCasePages } = useAssignedCaseQueue({
    tenantId,
    campaignId,
    session,
    setCasePageSize,
    casePageSize,
    caseRefreshVersion,
    setCurrentPage,
    currentPage,
  });
  const { availablePages, setAvailableCursor, availableQuery, queueError, hasError } =
    useAvailableCaseQueue({
      setNewCasesNotice,
      renderedAssignedTotalRef,
      lastNotifiedTotalRef,
      campaignId,
      tenantId,
      casesQuery,
    });
  const { claimMutation, openCase, claimEntireCase } = useCaseClaimActions({
    tenantId,
    session,
    navigate,
    campaignId,
    setClaimingCaseId,
    setCaseClaimErrors,
    queryClient,
  });
  const {
    cases,
    assignedCaseTotal,
    totalCasePages,
    pageCases,
    isPageLoading,
    pageRangeStart,
    pageRangeEnd,
  } = useAssignedCasePagination({
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
  });
  const available = availablePages;
  const availableGroups = groupAvailableByCase(available);
  const isLoading = (casesQuery.isLoading || availableQuery.isLoading) && available.length === 0;

  return {
    tenantId,
    campaignId,
    navigate,
    claimingCaseId,
    caseClaimErrors,
    reviewerId,
    casePageSize,
    setCasePageSize,
    setCaseRefreshVersion,
    currentPage,
    setCurrentPage,
    newCasesNotice,
    setNewCasesNotice,
    renderedAssignedTotalRef,
    lastNotifiedTotalRef,
    caseSubmitToast,
    campaignsQuery,
    campaign,
    setAvailableCursor,
    availableQuery,
    queueError,
    hasError,
    claimMutation,
    openCase,
    claimEntireCase,
    cases,
    assignedCaseTotal,
    totalCasePages,
    pageCases,
    isPageLoading,
    pageRangeStart,
    pageRangeEnd,
    available,
    availableGroups,
    isLoading,
  };
}
