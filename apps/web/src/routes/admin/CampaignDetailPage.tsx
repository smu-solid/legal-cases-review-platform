import { Link } from "react-router-dom";
import { CampaignAllocationSection } from "./campaignDetail/CampaignAllocationSection";
import { CampaignDetailHeader } from "./campaignDetail/CampaignDetailHeader";
import { CampaignLifecycleFeedback } from "./campaignDetail/CampaignLifecycleFeedback";
import { CampaignPoolSection } from "./campaignDetail/CampaignPoolSection";
import { CampaignReviewersSection } from "./campaignDetail/CampaignReviewersSection";
import { CampaignSettingsSection } from "./campaignDetail/CampaignSettingsSection";
import { CampaignTechnicalDetails } from "./campaignDetail/CampaignTechnicalDetails";
import { useCampaignDetail } from "./campaignDetail/useCampaignDetail";

import { AdminPage } from "../../components/admin/AdminLayout";
import { Spinner } from "../../components/Spinner";

import { CampaignCasesSection, CampaignProgressSection } from "./CampaignProgressSections";

export function CampaignDetailPage() {
  const model = useCampaignDetail();
  const {
    tenantId,
    canManageCampaigns,
    casePages,
    setCaseCursor,
    caseHasMore,
    campaignQuery,
    campaign,
    progress,
    casesQuery,
    selectedReviewerIds,
    campaignReviewerRows,
    campaignCanLoadCases,
  } = model;

  if (campaignQuery.isLoading) {
    return (
      <section className="page-panel" aria-labelledby="campaign-detail-title">
        <p className="muted" id="campaign-detail-title">
          <Spinner /> Loading campaign…
        </p>
      </section>
    );
  }

  if (campaignQuery.isError || !campaign) {
    return (
      <section className="page-panel" aria-labelledby="campaign-detail-title">
        <p className="eyebrow">Campaign</p>
        <h2 id="campaign-detail-title">Campaign not found</h2>
        <p>
          This campaign could not be loaded. <Link to={`/t/${tenantId}/admin`}>Back to admin</Link>
        </p>
      </section>
    );
  }

  return (
    <AdminPage ariaLabelledBy="campaign-detail-title">
      <CampaignDetailHeader {...model} campaign={campaign} />
      <CampaignLifecycleFeedback {...model} campaign={campaign} />
      <CampaignSettingsSection {...model} campaign={campaign} />

      {canManageCampaigns && campaignCanLoadCases ? <CampaignPoolSection {...model} /> : null}

      <CampaignReviewersSection {...model} campaign={campaign} />

      <CampaignAllocationSection {...model} />

      <CampaignProgressSection
        progress={progress}
        campaignReviewerRows={campaignReviewerRows}
        selectedReviewerIds={selectedReviewerIds}
      />
      <CampaignCasesSection
        cases={casePages}
        isLoading={casesQuery.isLoading}
        isFetching={casesQuery.isFetching}
        hasMore={caseHasMore}
        onLoadMore={() => setCaseCursor(casesQuery.data?.next_cursor ?? null)}
      />

      <CampaignTechnicalDetails {...model} campaign={campaign} />
    </AdminPage>
  );
}
