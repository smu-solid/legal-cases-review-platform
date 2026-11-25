import { Link } from "react-router-dom";
import { CampaignAuthoringForm } from "./dashboard/CampaignAuthoringForm";
import { CampaignListSection } from "./dashboard/CampaignListSection";
import { DashboardOverview } from "./dashboard/DashboardOverview";
import { ReviewerOnboardingSection } from "./dashboard/ReviewerOnboardingSection";
import { useAdminDashboard } from "./dashboard/useAdminDashboard";

import { AdminPage, AdminPageHeader, AdminSectionCard } from "../../components/admin/AdminLayout";

export function AdminDashboardPage() {
  const model = useAdminDashboard();
  const { tenantId, canManageCampaigns, rosterQuery, progressQuery, campaigns } = model;

  function renderCampaignAuthoring() {
    if (!canManageCampaigns) {
      return (
        <div className="notice compact" role="status">
          Creating or loading a campaign needs the campaign manager capability. Ask an administrator
          with campaign management rights.
        </div>
      );
    }

    return <CampaignAuthoringForm {...model} />;
  }

  return (
    <AdminPage ariaLabelledBy="admin-title">
      <AdminPageHeader
        eyebrow="Admin workspace"
        title="Campaign and reviewer operations"
        titleId="admin-title"
        actions={
          <Link className="secondary-button" to={`/t/${tenantId}/adjudication`}>
            Adjudication queue
          </Link>
        }
      />

      {rosterQuery.isError || progressQuery.isError ? (
        <div className="notice" role="alert">
          Admin data could not be loaded. The server remains the source of authorization truth.
        </div>
      ) : null}

      {campaigns.length > 0 ? <DashboardOverview {...model} /> : null}

      <ReviewerOnboardingSection {...model} />

      <CampaignListSection {...model} renderCampaignAuthoring={renderCampaignAuthoring} />

      <AdminSectionCard
        eyebrow="Adjudication"
        title="Resolve disagreements"
        titleId="adjudication-entry-title"
        id="admin-adjudication"
        summary="Adjudication opens in the authorized queue when reviewer submissions require a final decision."
        trailing={
          <Link className="primary-button" to={`/t/${tenantId}/adjudication`}>
            Open adjudication queue
          </Link>
        }
      />
    </AdminPage>
  );
}
