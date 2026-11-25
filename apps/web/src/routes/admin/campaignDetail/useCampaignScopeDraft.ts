import { useEffect, useMemo } from "react";
import type { CampaignReviewScopeInput } from "../../../api/types";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";

export function useCampaignScopeDraft({
  campaign,
  setNameDraft,
  setFieldSelectionDraft,
  setScopeGroupIdsDraft,
  fieldSelectionDraft,
  scopeGroupIdsDraft,
  loadFilterState,
}: {
  campaign: ReturnType<typeof useCampaignData>["campaign"];
  setNameDraft: ReturnType<typeof useCampaignControls>["setNameDraft"];
  setFieldSelectionDraft: ReturnType<typeof useCampaignControls>["setFieldSelectionDraft"];
  setScopeGroupIdsDraft: ReturnType<typeof useCampaignControls>["setScopeGroupIdsDraft"];
  fieldSelectionDraft: ReturnType<typeof useCampaignControls>["fieldSelectionDraft"];
  scopeGroupIdsDraft: ReturnType<typeof useCampaignControls>["scopeGroupIdsDraft"];
  loadFilterState: ReturnType<typeof useCampaignControls>["loadFilterState"];
}) {
  useEffect(() => {
    if (campaign) {
      setNameDraft(campaign.campaign_name);
      const groupIds = campaign.review_scope?.group_ids ?? [];
      setFieldSelectionDraft(groupIds.length > 0 ? "selected" : "all");
      setScopeGroupIdsDraft(groupIds);
    }
  }, [campaign, setFieldSelectionDraft, setNameDraft, setScopeGroupIdsDraft]);

  function toggleScopeGroupDraft(groupId: string) {
    setScopeGroupIdsDraft((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  }

  const reviewScopeDraft = useMemo<CampaignReviewScopeInput>(() => {
    const sourceFamilies = campaign?.review_scope?.source_families ?? [];
    const groupIds = fieldSelectionDraft === "all" ? [] : scopeGroupIdsDraft;
    return { source_families: sourceFamilies, group_ids: groupIds };
  }, [campaign?.review_scope?.source_families, fieldSelectionDraft, scopeGroupIdsDraft]);

  const savedSelectionMode = campaign?.case_id_selection ? "upload" : "filter";
  const editSelectionChanged = campaign
    ? loadFilterState.mode !== savedSelectionMode ||
      (loadFilterState.mode === "upload"
        ? JSON.stringify(loadFilterState.caseIdSelection) !==
            JSON.stringify(campaign.case_id_selection) ||
          loadFilterState.caseIdFileName !== campaign.case_id_selection_file_name
        : JSON.stringify(loadFilterState.caseFilter) !== JSON.stringify(campaign.case_filter))
    : false;
  return {
    toggleScopeGroupDraft,
    reviewScopeDraft,
    editSelectionChanged,
  };
}
