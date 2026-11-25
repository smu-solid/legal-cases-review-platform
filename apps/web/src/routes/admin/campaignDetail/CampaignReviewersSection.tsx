import { AdminSectionCard } from "../../../components/admin/AdminLayout";
import { InfoTooltip } from "../../../components/InfoTooltip";
import { reviewerLabel } from "../adminFormatters";
import { reviewerActionErrorMessage } from "../campaignDetailFormatters";
import { useCampaignAllocation } from "./useCampaignAllocation";
import { useCampaignData } from "./useCampaignData";
import { useCampaignReviewers } from "./useCampaignReviewers";

export function CampaignReviewersSection({
  campaign,
  selectedReviewerIds,
  reviewerActionError,
  reviewersLocked,
  eligibleReviewers,
  reviewerBoxInvalid,
  reviewerHasWork,
  reviewerHasLiveAccess,
  reviewerActionPending,
  toggleReviewer,
  allocationSummary,
}: {
  campaign: NonNullable<ReturnType<typeof useCampaignData>["campaign"]>;
  selectedReviewerIds: ReturnType<typeof useCampaignReviewers>["selectedReviewerIds"];
  reviewerActionError: ReturnType<typeof useCampaignReviewers>["reviewerActionError"];
  reviewersLocked: ReturnType<typeof useCampaignAllocation>["reviewersLocked"];
  eligibleReviewers: ReturnType<typeof useCampaignData>["eligibleReviewers"];
  reviewerBoxInvalid: ReturnType<typeof useCampaignAllocation>["reviewerBoxInvalid"];
  reviewerHasWork: ReturnType<typeof useCampaignReviewers>["reviewerHasWork"];
  reviewerHasLiveAccess: ReturnType<typeof useCampaignReviewers>["reviewerHasLiveAccess"];
  reviewerActionPending: ReturnType<typeof useCampaignReviewers>["reviewerActionPending"];
  toggleReviewer: ReturnType<typeof useCampaignReviewers>["toggleReviewer"];
  allocationSummary: ReturnType<typeof useCampaignData>["allocationSummary"];
}) {
  const sectionToExtract = (
    <AdminSectionCard
      eyebrow="Reviewers"
      title="Selected reviewers"
      titleId="reviewers-title"
      summary={
        <>
          Each case is reviewed by exactly {campaign.reviews_per_case} distinct reviewers. Select
          reviewers, preview the assignment plan, then publish.
        </>
      }
      trailing={<span className="status-chip">{selectedReviewerIds.size} selected</span>}
    >
      {reviewerActionError ? (
        <div className="form-error" role="alert">
          {reviewerActionErrorMessage(reviewerActionError)}
        </div>
      ) : null}
      <div className="notice compact" role="note">
        Adding or removing an eligible reviewer changes the next assignment plan only. Preview the
        plan and publish it to allocate unstarted cases; existing saved or submitted work is never
        moved.
      </div>
      {reviewersLocked ? (
        <div className="notice compact" role="status">
          This campaign is {campaign.status}; reviewers cannot be changed after closure.
        </div>
      ) : null}
      <fieldset
        className={
          "checkbox-stack" +
          (eligibleReviewers.length === 0 ? " is-disabled" : "") +
          (reviewerBoxInvalid ? " is-invalid" : "")
        }
        aria-invalid={reviewerBoxInvalid ? "true" : "false"}
        disabled={eligibleReviewers.length === 0 || reviewersLocked}
      >
        <legend>Eligible reviewers</legend>
        {eligibleReviewers.length === 0 ? (
          <p className="muted">
            0 — no active eligible reviewers yet. This is expected for a new campaign.
          </p>
        ) : (
          eligibleReviewers.map((reviewer) => {
            const selected = selectedReviewerIds.has(reviewer.user_id);
            const frozenForWork = selected && (reviewerHasWork.get(reviewer.user_id) ?? false);
            const unselectedWithAccess = !selected && reviewerHasLiveAccess.has(reviewer.user_id);
            return (
              <label
                key={reviewer.user_id}
                title={
                  frozenForWork
                    ? "Can't remove — this reviewer has saved or submitted work"
                    : undefined
                }
              >
                <input
                  checked={selected}
                  disabled={reviewerActionPending || frozenForWork}
                  type="checkbox"
                  onChange={() => toggleReviewer(reviewer.user_id, selected)}
                />
                {reviewerLabel(reviewer)}
                {frozenForWork ? (
                  <InfoTooltip
                    label={`Why ${reviewerLabel(reviewer)} can't be removed`}
                    text="This reviewer has saved or submitted review work in this campaign and cannot be removed. Keep them selected, or close the campaign instead."
                  />
                ) : null}
                {unselectedWithAccess ? (
                  <>
                    <span className="chip">Has access</span>
                    <InfoTooltip
                      label={`Why ${reviewerLabel(reviewer)} still has access`}
                      text="This reviewer is not on the current roster but still holds a claimed or submitted assignment in this campaign and can see it in their queue. Preview and publish an incremental update to move that work to the current roster."
                    />
                  </>
                ) : null}
              </label>
            );
          })
        )}
      </fieldset>
      {reviewerBoxInvalid ? (
        <p className="field-error-text" role="alert">
          {allocationSummary?.infeasible_message ??
            "At least 2 selected reviewers are required for this campaign's number of reviews per case."}
        </p>
      ) : null}
    </AdminSectionCard>
  );
  return sectionToExtract;
}
