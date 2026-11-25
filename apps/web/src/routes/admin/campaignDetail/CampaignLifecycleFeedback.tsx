import { Fragment } from "react";
import { AdminActionBar } from "../../../components/admin/AdminLayout";
import { Spinner } from "../../../components/Spinner";
import { completeErrorMessage, deleteErrorMessage } from "../campaignDetailFormatters";
import { useCampaignDetail } from "./useCampaignDetail";

export function CampaignLifecycleFeedback({
  completeRequested,
  campaign,
  completeMutation,
  setCompleteRequested,
  deleteResult,
  canManageCampaigns,
  deleteRequested,
  progress,
  deleteMutation,
  setDeleteRequested,
}: {
  completeRequested: ReturnType<typeof useCampaignDetail>["completeRequested"];
  campaign: NonNullable<ReturnType<typeof useCampaignDetail>["campaign"]>;
  completeMutation: ReturnType<typeof useCampaignDetail>["completeMutation"];
  setCompleteRequested: ReturnType<typeof useCampaignDetail>["setCompleteRequested"];
  deleteResult: ReturnType<typeof useCampaignDetail>["deleteResult"];
  canManageCampaigns: ReturnType<typeof useCampaignDetail>["canManageCampaigns"];
  deleteRequested: ReturnType<typeof useCampaignDetail>["deleteRequested"];
  progress: ReturnType<typeof useCampaignDetail>["progress"];
  deleteMutation: ReturnType<typeof useCampaignDetail>["deleteMutation"];
  setDeleteRequested: ReturnType<typeof useCampaignDetail>["setDeleteRequested"];
}) {
  const sectionToExtract = (
    <Fragment key="CampaignLifecycleFeedback">
      {completeRequested ? (
        <div
          className="confirm-panel"
          role="alertdialog"
          aria-label="Confirm mark campaign completed"
        >
          <p>
            Mark &ldquo;{campaign.campaign_name}&rdquo; completed? This is a one-way, display-only
            milestone — it does not change the campaign&rsquo;s published status and cannot be
            undone.
          </p>
          {completeMutation.isError ? (
            <div className="form-error" role="alert">
              {completeErrorMessage(completeMutation.error)}
            </div>
          ) : null}
          <AdminActionBar>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setCompleteRequested(false)}
            >
              Cancel
            </button>
            <button
              className="primary-button"
              disabled={completeMutation.isPending}
              type="button"
              onClick={() => completeMutation.mutate()}
            >
              {completeMutation.isPending ? (
                <>
                  <Spinner /> Marking completed…
                </>
              ) : (
                "Yes, mark completed"
              )}
            </button>
          </AdminActionBar>
        </div>
      ) : null}

      {deleteResult ? (
        <div className="notice compact" role="status">
          {deleteResult.already_closed
            ? "This campaign was already deleted by another administrator."
            : `Deleted — ${deleteResult.cases_returned_to_pool} case${deleteResult.cases_returned_to_pool === 1 ? "" : "s"} and ${deleteResult.units_returned_to_pool} review unit${deleteResult.units_returned_to_pool === 1 ? "" : "s"} returned to the pool.`}
        </div>
      ) : null}

      {canManageCampaigns && campaign?.status === "closed" && !deleteResult ? (
        <p className="muted" role="note">
          This campaign is closed and cannot be reopened.
        </p>
      ) : null}

      {deleteRequested ? (
        <div className="confirm-panel" role="alertdialog" aria-label="Confirm campaign delete">
          <p>
            Delete &ldquo;{campaign.campaign_name}&rdquo;? This closes the campaign permanently and
            returns its cases to the available pool. It cannot be undone.
          </p>
          {(progress?.total_assignments ?? 0) > 0 ? (
            <div className="notice compact" role="alert">
              Untouched assignments will be removed and the original cases returned to the pool.
              Deletion will be refused if any reviewer has saved or submitted work.
            </div>
          ) : null}
          {deleteMutation.isError &&
          deleteErrorMessage(deleteMutation.error) !== "confirmation_required" ? (
            <div className="form-error" role="alert">
              {deleteErrorMessage(deleteMutation.error)}
            </div>
          ) : null}
          <AdminActionBar>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setDeleteRequested(false)}
            >
              Cancel
            </button>
            <button
              className="danger-button"
              disabled={deleteMutation.isPending}
              type="button"
              onClick={() => deleteMutation.mutate(true)}
            >
              {deleteMutation.isPending ? (
                <>
                  <Spinner /> Deleting…
                </>
              ) : (
                "Yes, delete this campaign"
              )}
            </button>
          </AdminActionBar>
        </div>
      ) : null}
    </Fragment>
  );
  return sectionToExtract;
}
