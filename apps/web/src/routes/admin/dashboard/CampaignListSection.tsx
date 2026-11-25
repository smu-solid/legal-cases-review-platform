import type { JSX } from "react";
import { Link } from "react-router-dom";
import { Spinner } from "../../../components/Spinner";
import { AdminEmptyState, AdminSectionCard } from "../../../components/admin/AdminLayout";
import { useDashboardData } from "./useDashboardData";

export function CampaignListSection({
  progressQuery,
  closedCampaignCount,
  showClosedCampaigns,
  setShowClosedCampaigns,
  visibleCampaigns,
  tenantId,
  renderCampaignAuthoring,
  campaigns,
}: {
  progressQuery: ReturnType<typeof useDashboardData>["progressQuery"];
  closedCampaignCount: ReturnType<typeof useDashboardData>["closedCampaignCount"];
  showClosedCampaigns: ReturnType<typeof useDashboardData>["showClosedCampaigns"];
  setShowClosedCampaigns: ReturnType<typeof useDashboardData>["setShowClosedCampaigns"];
  visibleCampaigns: ReturnType<typeof useDashboardData>["visibleCampaigns"];
  tenantId: string;
  renderCampaignAuthoring: () => JSX.Element;
  campaigns: ReturnType<typeof useDashboardData>["campaigns"];
}) {
  const sectionToExtract = (
    <AdminSectionCard
      eyebrow="Campaigns"
      title="Your campaigns"
      titleId="campaigns-title"
      id="admin-campaign"
      summary="A campaign groups the cases, fields, reviewers, and assignments for one review batch. Open a campaign to edit it, select reviewers, preview and publish assignments, and monitor its progress."
      trailing={
        progressQuery.isLoading ? (
          <span className="status-chip">
            <Spinner /> Loading
          </span>
        ) : closedCampaignCount > 0 ? (
          <label className="show-closed-toggle">
            <input
              checked={showClosedCampaigns}
              type="checkbox"
              onChange={(event) => setShowClosedCampaigns(event.target.checked)}
            />
            {`Show closed (${closedCampaignCount})`}
          </label>
        ) : null
      }
    >
      {visibleCampaigns.length > 0 ? (
        <div className="admin-panel-grid">
          <div className="campaign-stack">
            {visibleCampaigns.map((campaign) => (
              <Link
                className="campaign-row"
                key={campaign.campaign_id}
                to={`/t/${tenantId}/admin/campaigns/${campaign.campaign_id}`}
              >
                <span>
                  <strong>{campaign.campaign_name}</strong>
                  <small>
                    {campaign.campaign_key} · {campaign.cases_total} cases ·{" "}
                    {campaign.reviewers_total} reviewers
                  </small>
                </span>
                <span className={"status-chip" + (campaign.completed ? " status-completed" : "")}>
                  {campaign.campaign_status}
                  {campaign.completed ? " · Completed" : ""}
                </span>
              </Link>
            ))}
          </div>
          {renderCampaignAuthoring()}
        </div>
      ) : campaigns.length > 0 ? (
        <div className="admin-panel-grid">
          <AdminEmptyState title="All campaigns are closed.">
            <p>
              All {closedCampaignCount} campaign{closedCampaignCount === 1 ? " is" : "s are"} closed
              and hidden by default. Use &ldquo;Show closed&rdquo; above to see them, or start a new
              campaign draft below.
            </p>
          </AdminEmptyState>
          {renderCampaignAuthoring()}
        </div>
      ) : (
        <AdminEmptyState title="No campaign yet.">
          <p>
            A campaign groups the cases, fields, reviewers, and assignments for one review batch.
            Create a campaign draft from the preloaded eligible case pool below to get started.
          </p>
          {renderCampaignAuthoring()}
        </AdminEmptyState>
      )}
    </AdminSectionCard>
  );
  return sectionToExtract;
}
