import { Link } from "react-router-dom";
import { AdminPageHeader } from "../../../components/admin/AdminLayout";
import { useCampaignAllocation } from "./useCampaignAllocation";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";

export function CampaignDetailHeader({
  campaign,
  tenantId,
  canManageCampaigns,
  campaignCanEdit,
  toggleCampaignEditing,
  editing,
  campaignCanComplete,
  setCompleteRequested,
  campaignCanDelete,
  setDeleteResult,
  setDeleteRequested,
}: {
  campaign: NonNullable<ReturnType<typeof useCampaignData>["campaign"]>;
  tenantId: string;
  canManageCampaigns: boolean;
  campaignCanEdit: ReturnType<typeof useCampaignAllocation>["campaignCanEdit"];
  toggleCampaignEditing: () => void;
  editing: ReturnType<typeof useCampaignControls>["editing"];
  campaignCanComplete: ReturnType<typeof useCampaignAllocation>["campaignCanComplete"];
  setCompleteRequested: ReturnType<typeof useCampaignControls>["setCompleteRequested"];
  campaignCanDelete: ReturnType<typeof useCampaignAllocation>["campaignCanDelete"];
  setDeleteResult: ReturnType<typeof useCampaignControls>["setDeleteResult"];
  setDeleteRequested: ReturnType<typeof useCampaignControls>["setDeleteRequested"];
}) {
  const sectionToExtract = (
    <AdminPageHeader
      eyebrow="Campaign"
      title={campaign.campaign_name}
      titleId="campaign-detail-title"
      subtitle={
        <p className="muted">
          <code>{campaign.campaign_key}</code> · {campaign.status}
          {campaign.completed ? (
            <span className="status-chip status-completed">Completed</span>
          ) : null}
        </p>
      }
      actions={
        <>
          <Link className="secondary-button" to={`/t/${tenantId}/admin`}>
            Back to admin
          </Link>
          {canManageCampaigns && campaignCanEdit ? (
            <button className="secondary-button" type="button" onClick={toggleCampaignEditing}>
              {editing
                ? "Cancel edit"
                : campaign.status === "draft"
                  ? "Edit draft"
                  : "Edit campaign"}
            </button>
          ) : null}
          {canManageCampaigns && campaignCanComplete ? (
            <button
              className="secondary-button"
              type="button"
              onClick={() => setCompleteRequested(true)}
            >
              Mark completed
            </button>
          ) : null}
          {canManageCampaigns && campaignCanDelete ? (
            <button
              className="danger-button"
              type="button"
              onClick={() => {
                setDeleteResult(null);
                setDeleteRequested(true);
              }}
            >
              Delete campaign
            </button>
          ) : null}
        </>
      }
    />
  );
  return sectionToExtract;
}
