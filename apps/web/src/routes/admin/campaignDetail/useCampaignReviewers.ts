import { useMutation } from "@tanstack/react-query";
import { useMemo } from "react";
import { addCampaignReviewer, removeCampaignReviewer } from "../../../api/admin";
import { useCampaignData } from "./useCampaignData";

export function useCampaignReviewers({
  tenantId,
  campaignId,
  csrfToken,
  invalidateCampaign,
  campaign,
  reviewerWorkloadQuery,
  rosterQuery,
}: {
  tenantId: string;
  campaignId: string;
  csrfToken: string | null;
  invalidateCampaign: () => void;
  campaign: ReturnType<typeof useCampaignData>["campaign"];
  reviewerWorkloadQuery: ReturnType<typeof useCampaignData>["reviewerWorkloadQuery"];
  rosterQuery: ReturnType<typeof useCampaignData>["rosterQuery"];
}) {
  const addReviewerMutation = useMutation({
    mutationFn: (reviewerId: string) =>
      addCampaignReviewer(tenantId, campaignId, reviewerId, csrfToken),
    onSuccess: invalidateCampaign,
  });

  const removeReviewerMutation = useMutation({
    mutationFn: (reviewerId: string) =>
      removeCampaignReviewer(tenantId, campaignId, reviewerId, csrfToken),
    onSuccess: invalidateCampaign,
  });

  const reviewerActionPending = addReviewerMutation.isPending || removeReviewerMutation.isPending;
  const reviewerActionError = addReviewerMutation.error ?? removeReviewerMutation.error;

  function toggleReviewer(reviewerId: string, currentlySelected: boolean) {
    if (currentlySelected) {
      removeReviewerMutation.mutate(reviewerId);
    } else {
      addReviewerMutation.mutate(reviewerId);
    }
  }

  const selectedReviewerIds = useMemo(
    () => new Set(campaign?.selected_reviewer_ids ?? []),
    [campaign?.selected_reviewer_ids],
  );
  // Same "has work" the backend remove guard enforces (saved/submitted/revision-requested review
  // work) -- lets the UI freeze the deselect control before the click instead of only reacting to
  // the eventual 422.
  const reviewerHasWork = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const item of reviewerWorkloadQuery.data?.items ?? []) {
      map.set(item.reviewer_id, item.has_work);
    }
    return map;
  }, [reviewerWorkloadQuery.data?.items]);
  // Live queue access, independent of the current roster: a reviewer with any claimed/submitted
  // assignment still sees this campaign (`_reviewer_campaign_ids`'s assignment fallback), even if
  // unchecked here. `released` doesn't count -- it means the unit moved away from them.
  const reviewerHasLiveAccess = useMemo(() => {
    const set = new Set<string>();
    for (const item of reviewerWorkloadQuery.data?.items ?? []) {
      if (item.claimed_count + item.submitted_count > 0) {
        set.add(item.reviewer_id);
      }
    }
    return set;
  }, [reviewerWorkloadQuery.data?.items]);
  const reviewerNameById = useMemo(
    () =>
      new Map(
        (rosterQuery.data?.items ?? []).map((reviewer) => [
          reviewer.user_id,
          reviewer.display_name,
        ]),
      ),
    [rosterQuery.data?.items],
  );
  const campaignReviewerRows = useMemo(() => {
    const rows = new Map(
      (reviewerWorkloadQuery.data?.items ?? []).map((item) => [item.reviewer_id, item]),
    );
    for (const reviewerId of selectedReviewerIds) {
      if (!rows.has(reviewerId)) {
        rows.set(reviewerId, {
          reviewer_id: reviewerId,
          total_assignments: 0,
          submitted_count: 0,
          claimed_count: 0,
          released_count: 0,
          has_work: false,
        });
      }
    }
    return [...rows.values()]
      .map((item) => ({
        ...item,
        reviewer_name: reviewerNameById.get(item.reviewer_id) ?? "Reviewer unavailable in roster",
      }))
      .sort((left, right) => left.reviewer_name.localeCompare(right.reviewer_name));
  }, [reviewerWorkloadQuery.data?.items, reviewerNameById, selectedReviewerIds]);
  return {
    reviewerActionPending,
    reviewerActionError,
    toggleReviewer,
    selectedReviewerIds,
    reviewerHasWork,
    reviewerHasLiveAccess,
    reviewerNameById,
    campaignReviewerRows,
  };
}
