import {
  AdminActionBar,
  AdminMetricGrid,
  AdminSectionCard,
} from "../../../components/admin/AdminLayout";
import { InfoTooltip } from "../../../components/InfoTooltip";
import { Spinner } from "../../../components/Spinner";
import {
  assignmentPreviewStatusLabel,
  previewCountsMessage,
  publishSummaryMessage,
} from "../adminFormatters";
import { useCampaignAllocation } from "./useCampaignAllocation";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";
import { useCampaignReviewers } from "./useCampaignReviewers";

export function CampaignAllocationSection({
  allocationSummary,
  allocationBlockedReason,
  hasExistingAssignments,
  incrementalPolicy,
  allocationPolicy,
  previewMutation,
  previewIsPublishable,
  publishMutation,
  previewResult,
  publishResult,
  reviewerNameById,
}: {
  allocationSummary: ReturnType<typeof useCampaignData>["allocationSummary"];
  allocationBlockedReason: ReturnType<typeof useCampaignAllocation>["allocationBlockedReason"];
  hasExistingAssignments: ReturnType<typeof useCampaignData>["hasExistingAssignments"];
  incrementalPolicy: ReturnType<typeof useCampaignAllocation>["incrementalPolicy"];
  allocationPolicy: ReturnType<typeof useCampaignAllocation>["allocationPolicy"];
  previewMutation: ReturnType<typeof useCampaignAllocation>["previewMutation"];
  previewIsPublishable: ReturnType<typeof useCampaignAllocation>["previewIsPublishable"];
  publishMutation: ReturnType<typeof useCampaignAllocation>["publishMutation"];
  previewResult: ReturnType<typeof useCampaignControls>["previewResult"];
  publishResult: ReturnType<typeof useCampaignControls>["publishResult"];
  reviewerNameById: ReturnType<typeof useCampaignReviewers>["reviewerNameById"];
}) {
  const sectionToExtract = (
    <AdminSectionCard eyebrow="Allocation" title="Assignment plan" titleId="allocation-title">
      {allocationSummary ? (
        <AdminMetricGrid>
          <div className="metric-card">
            <span>Cases selected</span>
            <strong>{allocationSummary.selected_cases}</strong>
          </div>
          <div className="metric-card">
            <span>Review units</span>
            <strong>{allocationSummary.review_units}</strong>
          </div>
          <div className="metric-card">
            <span>Reviews per case</span>
            <strong>{allocationSummary.reviews_per_case}</strong>
          </div>
          <div className="metric-card">
            <span>Selected reviewers</span>
            <strong>{allocationSummary.selected_reviewers}</strong>
          </div>
          <div className="metric-card">
            <span>
              Case assignments{" "}
              <InfoTooltip
                label="About: Case assignments"
                text="One case handed to one reviewer. This is how assignments are decided -- the planner allocates whole cases, and a reviewer never gets the same case twice. Cases selected x reviews per case."
              />
            </span>
            <strong>{allocationSummary.total_assignments}</strong>
          </div>
          <div className="metric-card">
            <span>
              Review-unit assignments{" "}
              <InfoTooltip
                label="About: Review-unit assignments"
                text="One review unit handed to one reviewer -- the actual items a reviewer works through, and what publishing creates. Each case assignment fans out over every in-scope field/relation of that case, so this is the larger number. Review units x reviews per case."
              />
            </span>
            <strong>{allocationSummary.total_unit_assignments}</strong>
          </div>
          <div className="metric-card">
            <span>Estimated cases per reviewer</span>
            <strong>{allocationSummary.estimated_assignments_per_reviewer}</strong>
          </div>
        </AdminMetricGrid>
      ) : null}
      <p className="fine-print">
        Case assignments = cases selected × reviews per case. Review-unit assignments = review units
        × reviews per case; that is the number publishing creates and the reviewer table below
        counts.
      </p>
      {allocationSummary?.selected_cases === 0 ? (
        <div className="form-error" role="alert">
          No cases or fields are in this campaign. Add cases from the available pool before
          previewing an assignment plan.
        </div>
      ) : allocationBlockedReason ? (
        <div className="notice" role="status">
          {allocationBlockedReason}
        </div>
      ) : null}

      <AdminActionBar>
        <button
          className="secondary-button"
          disabled={
            !(hasExistingAssignments ? incrementalPolicy : allocationPolicy) ||
            !allocationSummary?.feasible ||
            previewMutation.isPending
          }
          type="button"
          onClick={() => previewMutation.mutate()}
        >
          {previewMutation.isPending ? (
            <>
              <Spinner /> Previewing…
            </>
          ) : hasExistingAssignments ? (
            "Preview assignment updates"
          ) : (
            "Preview assignment plan"
          )}
        </button>
        <button
          className="primary-button"
          disabled={!previewIsPublishable || publishMutation.isPending}
          type="button"
          onClick={() => publishMutation.mutate()}
        >
          {publishMutation.isPending ? (
            <>
              <Spinner /> Publishing…
            </>
          ) : hasExistingAssignments ? (
            "Publish assignment updates"
          ) : (
            "Publish assignments"
          )}
        </button>
      </AdminActionBar>

      {previewResult ? (
        <div className="notice compact" role="status">
          <p>
            Assignment preview: {assignmentPreviewStatusLabel(previewResult.feasibility.status)} ·{" "}
            {"reviewer_workloads" in previewResult
              ? previewResult.reviewer_workloads.length
              : previewResult.workload_summaries.length}{" "}
            reviewer
            {("reviewer_workloads" in previewResult
              ? previewResult.reviewer_workloads.length
              : previewResult.workload_summaries.length) === 1
              ? ""
              : "s"}{" "}
            planned. {previewCountsMessage(previewResult)}
          </p>
          {previewResult.feasibility.errors.length > 0 ||
          previewResult.feasibility.warnings.length > 0 ? (
            <ul className="fine-print">
              {previewResult.feasibility.errors.map((issue) => (
                <li key={`error-${issue.code}`}>{issue.message}</li>
              ))}
              {previewResult.feasibility.warnings.map((issue) => (
                <li key={`warning-${issue.code}`}>{issue.message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {publishResult ? (
        <div className="notice" role="status">
          <p>{publishSummaryMessage(publishResult)}</p>
          {"revoked_reviewer_ids" in publishResult &&
          publishResult.revoked_reviewer_ids.length > 0 ? (
            <ul className="fine-print">
              {publishResult.revoked_reviewer_ids.map((reviewerId) => (
                <li key={reviewerId}>
                  {reviewerNameById.get(reviewerId) ?? "Reviewer unavailable in roster"} no longer
                  has access to this campaign.
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </AdminSectionCard>
  );
  return sectionToExtract;
}
