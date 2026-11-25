import { FormEvent } from "react";
import {
  AdminActionBar,
  AdminFormGrid,
  AdminSectionCard,
} from "../../../components/admin/AdminLayout";
import { Spinner } from "../../../components/Spinner";
import { CampaignCaseSelectionPanel } from "../CampaignCaseSelectionPanel";
import { editErrorMessage } from "../campaignDetailFormatters";
import { useCampaignData } from "./useCampaignData";
import type { useCampaignControls } from "./useCampaignDetail";
import { useCampaignLifecycle } from "./useCampaignLifecycle";
import { useCampaignPool } from "./useCampaignPool";
import { useCampaignScopeDraft } from "./useCampaignScopeDraft";

export function CampaignSettingsSection({
  editing,
  handleEditSubmit,
  editMutation,
  nameDraft,
  setNameDraft,
  campaign,
  loadFilterPanelVersion,
  tenantId,
  editSourceFamilies,
  csrfToken,
  canManageCampaigns,
  setLoadFilterState,
  fieldSelectionDraft,
  setFieldSelectionDraft,
  scopeGroups,
  scopeGroupIdsDraft,
  toggleScopeGroupDraft,
  editNeedsConfirm,
  setEditNeedsConfirm,
  editFilterReady,
}: {
  editing: ReturnType<typeof useCampaignControls>["editing"];
  handleEditSubmit: (event: FormEvent<HTMLFormElement>) => void;
  editMutation: ReturnType<typeof useCampaignLifecycle>["editMutation"];
  nameDraft: ReturnType<typeof useCampaignControls>["nameDraft"];
  setNameDraft: ReturnType<typeof useCampaignControls>["setNameDraft"];
  campaign: NonNullable<ReturnType<typeof useCampaignData>["campaign"]>;
  loadFilterPanelVersion: ReturnType<typeof useCampaignControls>["loadFilterPanelVersion"];
  tenantId: string;
  editSourceFamilies: ReturnType<typeof useCampaignPool>["editSourceFamilies"];
  csrfToken: string | null;
  canManageCampaigns: boolean;
  setLoadFilterState: ReturnType<typeof useCampaignControls>["setLoadFilterState"];
  fieldSelectionDraft: ReturnType<typeof useCampaignControls>["fieldSelectionDraft"];
  setFieldSelectionDraft: ReturnType<typeof useCampaignControls>["setFieldSelectionDraft"];
  scopeGroups: ReturnType<typeof useCampaignData>["scopeGroups"];
  scopeGroupIdsDraft: ReturnType<typeof useCampaignControls>["scopeGroupIdsDraft"];
  toggleScopeGroupDraft: ReturnType<typeof useCampaignScopeDraft>["toggleScopeGroupDraft"];
  editNeedsConfirm: ReturnType<typeof useCampaignControls>["editNeedsConfirm"];
  setEditNeedsConfirm: ReturnType<typeof useCampaignControls>["setEditNeedsConfirm"];
  editFilterReady: ReturnType<typeof useCampaignPool>["editFilterReady"];
}) {
  const sectionToExtract = (
    <AdminSectionCard
      eyebrow="Campaign"
      title={editing ? "Edit campaign" : "Campaign"}
      titleId="edit-campaign-title"
    >
      <form className="admin-subpanel" onSubmit={handleEditSubmit}>
        {editMutation.isError &&
        editErrorMessage(editMutation.error) !== "confirmation_required" ? (
          <div className="form-error" role="alert">
            {editErrorMessage(editMutation.error)}
          </div>
        ) : null}
        <AdminFormGrid>
          <label className={`campaign-edit-field${editing ? "" : " is-disabled"}`}>
            Campaign name
            <input
              disabled={!editing}
              value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)}
            />
          </label>
          <label className={`campaign-edit-field${editing ? "" : " is-disabled"}`}>
            Number of reviews per case
            <input
              className="frozen-input"
              type="number"
              min={2}
              max={20}
              disabled
              value={campaign.reviews_per_case}
            />
          </label>
        </AdminFormGrid>
        <CampaignCaseSelectionPanel
          key={`${loadFilterPanelVersion}-${editing ? "edit" : "view"}`}
          tenantId={tenantId}
          sourceFamilies={editSourceFamilies}
          csrfToken={csrfToken}
          enabled={canManageCampaigns && editing}
          initialFilter={campaign.case_filter}
          initialCaseIdSelection={campaign.case_id_selection}
          initialCaseIdFileName={campaign.case_id_selection_file_name}
          showExistingCasesWarning
          onStateChange={setLoadFilterState}
        />
        <AdminFormGrid>
          <label>
            Fields
            <select
              disabled={!editing}
              value={fieldSelectionDraft}
              onChange={(event) => setFieldSelectionDraft(event.target.value as "all" | "selected")}
            >
              <option value="all">All fields</option>
              <option value="selected">Selected fields</option>
            </select>
          </label>
        </AdminFormGrid>
        {fieldSelectionDraft === "selected" ? (
          <fieldset className="checkbox-stack">
            <legend>Selected field groups</legend>
            {scopeGroups.length === 0 ? (
              <p className="muted">No field groups available.</p>
            ) : (
              scopeGroups.map((group) => (
                <label key={group.group_id}>
                  <input
                    checked={scopeGroupIdsDraft.includes(group.group_id)}
                    disabled={!editing}
                    type="checkbox"
                    onChange={() => toggleScopeGroupDraft(group.group_id)}
                  />
                  {group.group_label}
                </label>
              ))
            )}
          </fieldset>
        ) : null}
        {editing && editNeedsConfirm ? (
          <div className="confirm-panel" role="alertdialog" aria-label="Confirm campaign edit">
            <p>
              You changed the case filters or uploaded file. Existing campaign cases remain
              unchanged, and the new selection will apply to future additions. Apply these changes?
            </p>
            <AdminActionBar>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setEditNeedsConfirm(false)}
              >
                Cancel
              </button>
              <button
                className="primary-button"
                disabled={editMutation.isPending || !editFilterReady}
                type="button"
                onClick={() => editMutation.mutate(true)}
              >
                Yes, apply the edit
              </button>
            </AdminActionBar>
          </div>
        ) : editing ? (
          <AdminActionBar>
            <button
              className="primary-button"
              disabled={editMutation.isPending || !editFilterReady}
              type="submit"
            >
              {editMutation.isPending ? (
                <>
                  <Spinner /> Saving…
                </>
              ) : (
                "Save changes"
              )}
            </button>
          </AdminActionBar>
        ) : null}
      </form>
    </AdminSectionCard>
  );
  return sectionToExtract;
}
