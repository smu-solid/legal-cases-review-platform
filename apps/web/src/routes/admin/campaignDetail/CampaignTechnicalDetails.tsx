import { caseFilterSummary } from "../campaignDetailFormatters";
import { useCampaignData } from "./useCampaignData";

export function CampaignTechnicalDetails({
  campaign,
  scopeGroupLabels,
}: {
  campaign: NonNullable<ReturnType<typeof useCampaignData>["campaign"]>;
  scopeGroupLabels: ReturnType<typeof useCampaignData>["scopeGroupLabels"];
}) {
  const sectionToExtract = (
    <details className="technical-details">
      <summary>Technical details</summary>
      <div className="admin-panel-grid">
        <div>
          <h4>Selected field groups</h4>
          <p className="muted">
            {campaign.review_scope?.group_ids?.length
              ? campaign.review_scope.group_ids
                  .map((id) => scopeGroupLabels.get(id) ?? id)
                  .join(", ")
              : "All field groups"}
          </p>
        </div>
        <div>
          <h4>Selected review kinds</h4>
          <p className="muted">
            {campaign.review_scope?.review_kinds?.length
              ? campaign.review_scope.review_kinds.join(", ")
              : "All review kinds"}
          </p>
        </div>
        <div>
          <h4>Filter applied / file uploaded</h4>
          <p className="muted">
            {campaign.case_id_selection
              ? (campaign.case_id_selection_file_name ?? "Uploaded file name unavailable")
              : caseFilterSummary(campaign.case_filter)}
          </p>
        </div>
      </div>
    </details>
  );
  return sectionToExtract;
}
