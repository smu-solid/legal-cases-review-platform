import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  previewAllocationRun,
  previewIncrementalAllocation,
  publishAllocationPlan,
  publishIncrementalAllocation,
} from "../../../api/admin";
import type {
  AllocationPolicyInput,
  AllocationPreviewResponse,
  AllocationPublishResponse,
  IncrementalPolicyInput,
  IncrementalPreviewResponse,
  IncrementalPublishResponse,
} from "../../../api/types";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";

const allocationVersion = "reviewer-allocation/v1";

export function useCampaignAllocation({
  campaign,
  eligibleReviewers,
  allocationSummary,
  selectedReviewerIds,
  hasExistingAssignments,
  allocationRunsQuery,
  basePublishedRun,
  tenantId,
  campaignId,
  csrfToken,
  setPreviewResult,
  setPublishResult,
  previewResult,
  invalidateCampaign,
  queryClient,
}: {
  campaign: ReturnType<typeof useCampaignData>["campaign"];
  eligibleReviewers: ReturnType<typeof useCampaignData>["eligibleReviewers"];
  allocationSummary: ReturnType<typeof useCampaignData>["allocationSummary"];
  selectedReviewerIds: Set<string>;
  hasExistingAssignments: ReturnType<typeof useCampaignData>["hasExistingAssignments"];
  allocationRunsQuery: ReturnType<typeof useCampaignData>["allocationRunsQuery"];
  basePublishedRun: ReturnType<typeof useCampaignData>["basePublishedRun"];
  tenantId: string;
  campaignId: string;
  csrfToken: string | null;
  setPreviewResult: ReturnType<typeof useCampaignControls>["setPreviewResult"];
  setPublishResult: ReturnType<typeof useCampaignControls>["setPublishResult"];
  previewResult: ReturnType<typeof useCampaignControls>["previewResult"];
  invalidateCampaign: () => void;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const reviewersLocked = campaign
    ? !["draft", "planned", "published"].includes(campaign.status)
    : false;
  const campaignCanLoadCases = campaign?.status !== "closed";
  const campaignCanEdit = campaign
    ? ["draft", "planned", "published"].includes(campaign.status)
    : false;
  const campaignCanDelete = campaign
    ? ["draft", "planned", "published"].includes(campaign.status)
    : false;
  const campaignCanComplete = campaign?.status === "published" && !campaign.completed;
  // Only highlight the checkbox box itself when there are eligible reviewers to pick from but too
  // few are selected -- an empty roster already gets its own dedicated "0 - no active eligible
  // reviewers yet" copy below, and duplicating the invalid state there would be redundant.
  const reviewerBoxInvalid =
    eligibleReviewers.length > 0 &&
    (allocationSummary?.infeasible_reason === "insufficient_reviewers" ||
      allocationSummary?.infeasible_reason === "no_selected_reviewers");
  // Plain-language reason the allocation actions are disabled, in priority order: no cases to
  // allocate outranks no reviewers, which outranks a generic infeasibility message from the
  // backend. `null` means the plan is feasible and the buttons are enabled.
  const allocationBlockedReason =
    !allocationSummary || allocationSummary.selected_cases === 0
      ? "No review units available. Load cases before previewing assignments."
      : selectedReviewerIds.size === 0
        ? "Add more reviewers before publishing assignments."
        : hasExistingAssignments &&
            !allocationRunsQuery.isLoading &&
            !allocationRunsQuery.isError &&
            !basePublishedRun
          ? "Assignments exist, but no published base allocation run was found. Incremental preview is unavailable; ask an administrator to inspect allocation history."
          : !allocationSummary.feasible
            ? allocationSummary.infeasible_message
            : null;

  const allocationPolicy = useMemo<AllocationPolicyInput | null>(() => {
    if (!campaign || !allocationSummary || allocationSummary.selected_cases === 0) {
      return null;
    }
    return {
      subject_kind: "case",
      review_kind: "metadata_field",
      reviewer_ids: campaign.selected_reviewer_ids,
      target_distinct_subjects: allocationSummary.selected_cases,
      target_per_reviewer_workload: Math.max(
        1,
        allocationSummary.estimated_assignments_per_reviewer,
      ),
      // Every case needs exactly reviews_per_case (number of reviews per case) distinct reviewers
      // from the whole pool. That is uniform_reviews_per_subject, not
      // target_pairwise_overlap/target_global_overlap -- those size the engine's hub/pair-sharing
      // sampling layers (a different concept: subjects shared by a specific reviewer pair or the
      // whole pool) and previously caused campaigns with more cases than reviewers to be
      // misreported as infeasible.
      target_pairwise_overlap: 0,
      target_global_overlap: 0,
      uniform_reviews_per_subject: allocationSummary.reviews_per_case,
      rolling_window_size: allocationSummary.selected_cases,
      rolling_window_stride: Math.max(1, Math.floor(allocationSummary.selected_cases / 2)),
      hub_priority_count: 0,
      random_seed: `campaign-${campaign.campaign_key.replace(/[^A-Za-z0-9._:-]/g, "-")}`,
      allocation_policy_version: allocationVersion,
      metric_weights: {},
    };
  }, [allocationSummary, campaign]);

  const incrementalPolicy = useMemo<IncrementalPolicyInput | null>(() => {
    if (!campaign || !allocationSummary || !basePublishedRun) {
      return null;
    }
    return {
      allocation_policy_version: "reviewer-allocation/v1",
      base_run_id: basePublishedRun.run_id,
      min_reviews_per_subject: allocationSummary.reviews_per_case,
      movement_policy: {
        allow_rebalance_unclaimed: true,
        allow_rebalance_claimed: true,
        allow_rebalance_draft: false,
      },
      random_seed: `campaign-${campaign.campaign_key.replace(/[^A-Za-z0-9._:-]/g, "-")}`,
      review_kind: "metadata_field",
      reviewer_ids: campaign.selected_reviewer_ids,
      subject_kind: "case",
    };
  }, [allocationSummary, basePublishedRun, campaign]);

  const previewMutation = useMutation<AllocationPreviewResponse | IncrementalPreviewResponse>({
    mutationFn: () =>
      hasExistingAssignments
        ? previewIncrementalAllocation(tenantId, campaignId, incrementalPolicy!, csrfToken)
        : previewAllocationRun(tenantId, campaignId, allocationPolicy!, csrfToken),
    onSuccess: (response) => {
      setPreviewResult(response);
      setPublishResult(null);
    },
  });

  // The pre-preview estimate (allocationSummary) only counts *selected* reviewer ids -- it can't
  // see server-side reviewer deactivation, so a "feasible" estimate can still come back
  // blocked_by_reviewer_pool/infeasible from the real engine. Gate Publish on the real preview's
  // own feasibility, not just its presence.
  const previewIsPublishable =
    previewResult?.feasibility.status === "feasible" ||
    previewResult?.feasibility.status === "feasible_with_warnings";

  // Publishing persists the plan and publishes it in the same request -- the admin never sees or
  // needs a separate "persisted but unpublished" run; that is a backend durability/audit detail
  // (drift guard, idempotent replay), not a product step.
  const publishMutation = useMutation<AllocationPublishResponse | IncrementalPublishResponse>({
    mutationFn: () =>
      hasExistingAssignments
        ? publishIncrementalAllocation(tenantId, campaignId, incrementalPolicy!, csrfToken)
        : publishAllocationPlan(tenantId, campaignId, allocationPolicy!, csrfToken),
    onSuccess: (response) => {
      setPublishResult(response);
      invalidateCampaign();
      // Publishing creates assignments reviewers can now see -- refresh their queues too, not
      // just this admin's own view.
      void queryClient.invalidateQueries({ queryKey: ["reviewer-campaign-queue", tenantId] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue", tenantId] });
      void queryClient.invalidateQueries({ queryKey: ["allocation-runs", tenantId, campaignId] });
      void queryClient.invalidateQueries({
        queryKey: ["campaign-reviewer-workload", tenantId, campaignId],
      });
    },
  });
  return {
    reviewersLocked,
    campaignCanLoadCases,
    campaignCanEdit,
    campaignCanDelete,
    campaignCanComplete,
    reviewerBoxInvalid,
    allocationBlockedReason,
    allocationPolicy,
    incrementalPolicy,
    previewMutation,
    previewIsPublishable,
    publishMutation,
  };
}
