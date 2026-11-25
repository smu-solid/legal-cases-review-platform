import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError } from "../../../api/client";
import { listReviewQueue } from "../../../api/reviewer";
import type { ReviewQueueItem } from "../../../api/types";
import { useAssignedCaseQueue } from "./useAssignedCaseQueue";
import type { useReviewerQueueState } from "./useReviewerQueue";

export function useAvailableCaseQueue({
  setNewCasesNotice,
  renderedAssignedTotalRef,
  lastNotifiedTotalRef,
  campaignId,
  tenantId,
  casesQuery,
}: {
  setNewCasesNotice: ReturnType<typeof useReviewerQueueState>["setNewCasesNotice"];
  renderedAssignedTotalRef: ReturnType<typeof useReviewerQueueState>["renderedAssignedTotalRef"];
  lastNotifiedTotalRef: ReturnType<typeof useReviewerQueueState>["lastNotifiedTotalRef"];
  campaignId: string;
  tenantId: string;
  casesQuery: ReturnType<typeof useAssignedCaseQueue>["casesQuery"];
}) {
  const [availablePages, setAvailablePages] = useState<ReviewQueueItem[]>([]);
  const [availableCursor, setAvailableCursor] = useState<string | null>(null);

  useEffect(() => {
    setAvailablePages([]);
    setAvailableCursor(null);
    setNewCasesNotice(null);
    renderedAssignedTotalRef.current = null;
    lastNotifiedTotalRef.current = null;
  }, [campaignId, lastNotifiedTotalRef, renderedAssignedTotalRef, setNewCasesNotice]);

  const availableQuery = useQuery({
    queryKey: ["review-queue", tenantId, campaignId, "available", availableCursor],
    queryFn: () =>
      listReviewQueue(tenantId, {
        campaignId,
        assignmentStatus: "available",
        cursor: availableCursor,
        limit: 25,
      }),
    enabled: Boolean(tenantId && campaignId),
    retry: false,
  });

  useEffect(() => {
    if (!availableQuery.data) {
      return;
    }
    setAvailablePages((current) =>
      availableCursor === null
        ? availableQuery.data.items
        : [...current, ...availableQuery.data.items],
    );
    // availableCursor intentionally excluded: this effect reacts to new page data, not cursor changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableQuery.data]);

  const queueError =
    casesQuery.error instanceof ApiError && casesQuery.error.status === 403
      ? "You are not assigned reviewer access for this campaign."
      : availableQuery.error instanceof ApiError && availableQuery.error.status === 403
        ? "You are not assigned reviewer access for this campaign."
        : "The review queue could not be loaded right now. Retry in a moment, or contact an administrator if the problem continues.";
  const hasError = casesQuery.isError || availableQuery.isError;
  return { availablePages, setAvailableCursor, availableQuery, queueError, hasError };
}
