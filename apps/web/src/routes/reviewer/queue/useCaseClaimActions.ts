import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../../api/client";
import { claimReviewUnit } from "../../../api/reviewer";
import type { ReviewerCaseQueueItem, ReviewQueueItem } from "../../../api/types";
import { useAuthSession } from "../../../auth/authSession";
import { AvailableCaseGroup } from "./queueState";
import type { useReviewerQueueState } from "./useReviewerQueue";

export function useCaseClaimActions({
  tenantId,
  session,
  navigate,
  campaignId,
  setClaimingCaseId,
  setCaseClaimErrors,
  queryClient,
}: {
  tenantId: string;
  session: ReturnType<typeof useAuthSession>;
  navigate: ReturnType<typeof useNavigate>;
  campaignId: string;
  setClaimingCaseId: ReturnType<typeof useReviewerQueueState>["setClaimingCaseId"];
  setCaseClaimErrors: ReturnType<typeof useReviewerQueueState>["setCaseClaimErrors"];
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const claimMutation = useMutation({
    mutationFn: (item: ReviewQueueItem) =>
      claimReviewUnit(
        tenantId,
        {
          review_unit_id: item.review_unit_id,
          subject_kind: "case",
          review_kind: item.review_kind,
          campaign_id: item.campaign_id,
        },
        session.csrfToken,
      ),
    onSuccess: (claim) => {
      navigate(`/t/${tenantId}/review/task/${claim.assignment_id}?campaignId=${campaignId}`);
    },
  });

  function openCase(item: ReviewerCaseQueueItem) {
    navigate(`/t/${tenantId}/review/task/${item.anchor_assignment_id}?campaignId=${campaignId}`);
  }

  async function claimEntireCase(group: AvailableCaseGroup) {
    setClaimingCaseId(group.caseId);
    setCaseClaimErrors((current) => {
      const next = { ...current };
      delete next[group.caseId];
      return next;
    });
    let lastAssignmentId: string | null = null;
    let hadError = false;
    for (const item of group.items.filter((field) => !field.assignment_id)) {
      try {
        const claim = await claimReviewUnit(
          tenantId,
          {
            review_unit_id: item.review_unit_id,
            subject_kind: "case",
            review_kind: item.review_kind,
            campaign_id: item.campaign_id,
          },
          session.csrfToken,
        );
        lastAssignmentId = claim.assignment_id;
      } catch (error) {
        const message =
          error instanceof ApiError && error.status === 409
            ? `"${item.safe_field_label}" was claimed by someone else first. The rest of this case's fields are still available.`
            : `"${item.safe_field_label}" could not be claimed. Retry in a moment.`;
        setCaseClaimErrors((current) => ({ ...current, [group.caseId]: message }));
        hadError = true;
        break;
      }
    }
    setClaimingCaseId(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["reviewer-case-queue", tenantId, campaignId] }),
      queryClient.invalidateQueries({ queryKey: ["review-queue", tenantId, campaignId] }),
      queryClient.invalidateQueries({ queryKey: ["reviewer-campaign-queue", tenantId] }),
    ]);
    // Only jump into the workspace once every field claimed cleanly -- a partial failure keeps the
    // reviewer on the queue page so the error message (which field, and that the rest is still
    // claimable) stays visible instead of vanishing behind a navigation.
    if (lastAssignmentId && !hadError) {
      navigate(`/t/${tenantId}/review/task/${lastAssignmentId}?campaignId=${campaignId}`);
    }
  }
  return { claimMutation, openCase, claimEntireCase };
}
