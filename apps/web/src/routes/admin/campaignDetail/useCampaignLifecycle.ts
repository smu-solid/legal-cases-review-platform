import { useMutation, useQueryClient } from "@tanstack/react-query";
import { completeCampaign, deleteCampaign, editCampaign } from "../../../api/admin";
import { editErrorMessage } from "../campaignDetailFormatters";
import type { useCampaignControls } from "./useCampaignDetail";

export function useCampaignLifecycle({
  tenantId,
  campaignId,
  nameDraft,
  reviewScopeDraft,
  editSelectionChanged,
  loadFilterState,
  csrfToken,
  queryClient,
  setEditing,
  setEditNeedsConfirm,
  invalidateCampaign,
  setDeleteRequested,
  setDeleteResult,
  setCompleteRequested,
}: {
  tenantId: string;
  campaignId: string;
  nameDraft: ReturnType<typeof useCampaignControls>["nameDraft"];
  reviewScopeDraft: { group_ids?: string[]; review_kinds?: string[]; source_families?: string[] };
  editSelectionChanged: boolean;
  loadFilterState: ReturnType<typeof useCampaignControls>["loadFilterState"];
  csrfToken: string | null;
  queryClient: ReturnType<typeof useQueryClient>;
  setEditing: ReturnType<typeof useCampaignControls>["setEditing"];
  setEditNeedsConfirm: ReturnType<typeof useCampaignControls>["setEditNeedsConfirm"];
  invalidateCampaign: () => void;
  setDeleteRequested: ReturnType<typeof useCampaignControls>["setDeleteRequested"];
  setDeleteResult: ReturnType<typeof useCampaignControls>["setDeleteResult"];
  setCompleteRequested: ReturnType<typeof useCampaignControls>["setCompleteRequested"];
}) {
  const editMutation = useMutation({
    mutationFn: (confirm: boolean) =>
      editCampaign(
        tenantId,
        campaignId,
        {
          campaign_name: nameDraft.trim(),
          review_scope: reviewScopeDraft,
          ...(editSelectionChanged
            ? loadFilterState.mode === "filter"
              ? {
                  case_filter: loadFilterState.caseFilter,
                  applied_filter_token: loadFilterState.filterResult?.applied_filter_token,
                }
              : {
                  case_id_selection: loadFilterState.caseIdSelection,
                  applied_case_id_token: loadFilterState.caseIdResult?.applied_case_id_token,
                  case_id_selection_file_name: loadFilterState.caseIdFileName,
                }
            : {}),
          confirm,
        },
        csrfToken,
      ),
    onSuccess: (updatedCampaign) => {
      queryClient.setQueryData(["campaign-detail", tenantId, campaignId], updatedCampaign);
      setEditing(false);
      setEditNeedsConfirm(false);
      invalidateCampaign();
    },
    onError: (error) => {
      if (editErrorMessage(error) === "confirmation_required") {
        setEditNeedsConfirm(true);
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (confirm: boolean) => deleteCampaign(tenantId, campaignId, confirm, csrfToken),
    onSuccess: (response) => {
      setDeleteRequested(false);
      setDeleteResult(response);
      invalidateCampaign();
    },
  });

  const completeMutation = useMutation({
    mutationFn: () => completeCampaign(tenantId, campaignId, csrfToken),
    onSuccess: () => {
      setCompleteRequested(false);
      invalidateCampaign();
    },
  });
  return { editMutation, deleteMutation, completeMutation };
}
