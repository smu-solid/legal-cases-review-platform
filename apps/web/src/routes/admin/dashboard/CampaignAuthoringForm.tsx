import { Spinner } from "../../../components/Spinner";
import {
  AdminActionBar,
  AdminFormGrid,
  AdminMetricGrid,
} from "../../../components/admin/AdminLayout";
import { CampaignCaseSelectionPanel } from "../CampaignCaseSelectionPanel";
import { campaignActionErrorMessage } from "../adminFormatters";
import type { useDashboardFormState } from "./useAdminDashboard";
import { useCampaignAuthoring } from "./useCampaignAuthoring";
import { useDashboardData } from "./useDashboardData";

export function CampaignAuthoringForm({
  createCampaignMutation,
  campaignKey,
  handleCampaignKeyChange,
  campaignName,
  handleCampaignNameChange,
  minimumReviews,
  filterPanelVersion,
  tenantId,
  csrfToken,
  canManageCampaigns,
  setFilterState,
  fieldSelection,
  setFieldSelection,
  caseCountMode,
  setCaseCountMode,
  caseCount,
  setCaseCount,
  scopeGroups,
  selectedScopeGroupIds,
  toggleScopeGroup,
  synthesizeMissing,
  setSynthesizeMissing,
  availabilityQuery,
  availability,
  projectedCampaignCases,
  scopeGroupLabels,
  availabilityInfeasible,
  needsConfirmation,
  campaignActionPending,
  caseFilterReady,
  canSubmitCampaign,
}: {
  createCampaignMutation: ReturnType<typeof useCampaignAuthoring>["createCampaignMutation"];
  campaignKey: ReturnType<typeof useDashboardFormState>["campaignKey"];
  handleCampaignKeyChange: ReturnType<typeof useCampaignAuthoring>["handleCampaignKeyChange"];
  campaignName: ReturnType<typeof useDashboardFormState>["campaignName"];
  handleCampaignNameChange: ReturnType<typeof useCampaignAuthoring>["handleCampaignNameChange"];
  minimumReviews: ReturnType<typeof useDashboardFormState>["minimumReviews"];
  filterPanelVersion: ReturnType<typeof useDashboardFormState>["filterPanelVersion"];
  tenantId: string;
  csrfToken: string | null;
  canManageCampaigns: boolean;
  setFilterState: ReturnType<typeof useDashboardFormState>["setFilterState"];
  fieldSelection: ReturnType<typeof useDashboardFormState>["fieldSelection"];
  setFieldSelection: ReturnType<typeof useDashboardFormState>["setFieldSelection"];
  caseCountMode: ReturnType<typeof useDashboardFormState>["caseCountMode"];
  setCaseCountMode: ReturnType<typeof useDashboardFormState>["setCaseCountMode"];
  caseCount: ReturnType<typeof useDashboardFormState>["caseCount"];
  setCaseCount: ReturnType<typeof useDashboardFormState>["setCaseCount"];
  scopeGroups: ReturnType<typeof useDashboardData>["scopeGroups"];
  selectedScopeGroupIds: ReturnType<typeof useDashboardFormState>["selectedScopeGroupIds"];
  toggleScopeGroup: ReturnType<typeof useCampaignAuthoring>["toggleScopeGroup"];
  synthesizeMissing: ReturnType<typeof useDashboardFormState>["synthesizeMissing"];
  setSynthesizeMissing: ReturnType<typeof useDashboardFormState>["setSynthesizeMissing"];
  availabilityQuery: ReturnType<typeof useCampaignAuthoring>["availabilityQuery"];
  availability: ReturnType<typeof useCampaignAuthoring>["availability"];
  projectedCampaignCases: ReturnType<typeof useCampaignAuthoring>["projectedCampaignCases"];
  scopeGroupLabels: ReturnType<typeof useDashboardData>["scopeGroupLabels"];
  availabilityInfeasible: ReturnType<typeof useCampaignAuthoring>["availabilityInfeasible"];
  needsConfirmation: ReturnType<typeof useCampaignAuthoring>["needsConfirmation"];
  campaignActionPending: ReturnType<typeof useCampaignAuthoring>["campaignActionPending"];
  caseFilterReady: ReturnType<typeof useCampaignAuthoring>["caseFilterReady"];
  canSubmitCampaign: ReturnType<typeof useCampaignAuthoring>["canSubmitCampaign"];
}) {
  const sectionToExtract = (
    <div className="admin-subpanel campaign-authoring">
      <h4>Create campaign draft</h4>
      {createCampaignMutation.isError ? (
        <div className="form-error" role="alert">
          {campaignActionErrorMessage(createCampaignMutation.error)}
        </div>
      ) : null}
      <AdminFormGrid>
        <label>
          Campaign key
          <input
            name="campaign_key"
            value={campaignKey}
            onChange={(event) => handleCampaignKeyChange(event.target.value)}
          />
        </label>
        <label>
          Campaign name
          <input
            name="campaign_name"
            value={campaignName}
            onChange={(event) => handleCampaignNameChange(event.target.value)}
          />
        </label>
        <label>
          Number of reviews per case
          <input
            className="frozen-input"
            type="number"
            min={2}
            name="reviews_per_case"
            value={minimumReviews}
            disabled
          />
        </label>
      </AdminFormGrid>
      <CampaignCaseSelectionPanel
        key={filterPanelVersion}
        tenantId={tenantId}
        csrfToken={csrfToken}
        enabled={canManageCampaigns}
        onStateChange={setFilterState}
      />
      <AdminFormGrid>
        <label>
          Fields
          <select
            value={fieldSelection}
            onChange={(event) => setFieldSelection(event.target.value as "all" | "selected")}
          >
            <option value="all">All fields</option>
            <option value="selected">Selected fields</option>
          </select>
        </label>
        <label>
          Case count
          <select
            value={caseCountMode}
            onChange={(event) => setCaseCountMode(event.target.value as "all" | "count")}
          >
            <option value="all">All eligible cases</option>
            <option value="count">Exact number</option>
          </select>
        </label>
        {caseCountMode === "count" ? (
          <label>
            Requested cases
            <input
              type="number"
              min={1}
              name="case_count"
              value={caseCount}
              onChange={(event) => setCaseCount(Number(event.target.value) || 0)}
            />
          </label>
        ) : null}
      </AdminFormGrid>
      {fieldSelection === "selected" ? (
        <fieldset className="checkbox-stack">
          <legend>Field groups</legend>
          {scopeGroups.map((group) => (
            <label key={group.group_id}>
              <input
                type="checkbox"
                checked={selectedScopeGroupIds.includes(group.group_id)}
                onChange={() => toggleScopeGroup(group.group_id)}
              />
              {group.group_label}
            </label>
          ))}
          {scopeGroups.length === 0 ? (
            <p className="muted">No field groups available from the scope catalog yet.</p>
          ) : null}
        </fieldset>
      ) : null}
      <label className="checkbox-inline">
        <input
          type="checkbox"
          checked={synthesizeMissing}
          onChange={(event) => setSynthesizeMissing(event.target.checked)}
        />
        Include missing fields as review tasks — a case that is missing a selected field is kept
        (not excluded), and reviewers get an explicit “no value extracted” task for it.
      </label>
      {availabilityQuery.isLoading ? (
        <p className="muted">
          <Spinner /> Checking availability…
        </p>
      ) : null}
      {availability ? (
        <AdminMetricGrid>
          <div className="metric-card">
            <span>Available in pool</span>
            <strong>{availability.source_pool_cases_count} cases</strong>
          </div>
          <div className="metric-card">
            <span>Matches case selection</span>
            <strong>{availability.case_filter_matching_count} cases</strong>
          </div>
          <div className="metric-card">
            <span>New campaign total</span>
            <strong>{projectedCampaignCases} cases</strong>
          </div>
        </AdminMetricGrid>
      ) : null}
      {availability?.overlap_cases_count ? (
        <div className="notice compact" role="alert">
          <strong>Some fields are already in other campaigns.</strong>
          <p>
            {fieldSelection === "all"
              ? "Those fields will be omitted from this new campaign; each affected case will include only its remaining available fields."
              : "Affected cases cannot include every selected field and will be excluded unless the remaining-fields-only option is offered and confirmed."}
          </p>
          {availability.overlap_campaigns?.length ? (
            <ul>
              {availability.overlap_campaigns.map((item) => (
                <li key={item.campaign_id}>
                  <strong>{item.campaign_name}</strong> (<code>{item.campaign_key}</code>):{" "}
                  {(item.group_counts ?? [])
                    .map(
                      (group) =>
                        `${scopeGroupLabels.get(group.group_id) ?? group.group_id} (${group.cases_count} case${group.cases_count === 1 ? "" : "s"})`,
                    )
                    .join(", ")}
                </li>
              ))}
            </ul>
          ) : (
            <p>{availability.overlap_cases_count} affected cases.</p>
          )}
          <p>The existing campaigns and their fields will not be changed.</p>
        </div>
      ) : null}
      {availabilityInfeasible ? (
        <div className="form-error" role="alert">
          {availability?.infeasible_message ??
            "No cases or fields are available for this selection."}
          {availability?.fields_fully_exhausted.length ? (
            <> Exhausted field groups: {availability.fields_fully_exhausted.join(", ")}.</>
          ) : null}
        </div>
      ) : null}
      {needsConfirmation && availability ? (
        <div className="notice compact" role="alert">
          {availability.infeasible_message ??
            `Only ${availability.eligible_cases_count} eligible cases are available for this field scope.`}
          <AdminActionBar>
            <button
              className="primary-button"
              disabled={campaignActionPending || !caseFilterReady}
              type="button"
              onClick={() => createCampaignMutation.mutate(true)}
            >
              Create with {availability.eligible_cases_count} case
              {availability.eligible_cases_count === 1 ? "" : "s"}
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setFieldSelection("all")}
            >
              Adjust selected fields
            </button>
          </AdminActionBar>
        </div>
      ) : null}
      <AdminActionBar>
        <button
          className="primary-button"
          disabled={
            !canSubmitCampaign ||
            campaignActionPending ||
            needsConfirmation ||
            availabilityInfeasible ||
            !availability ||
            !caseFilterReady
          }
          type="button"
          onClick={() => createCampaignMutation.mutate(false)}
        >
          {createCampaignMutation.isPending ? (
            <>
              <Spinner /> Creating…
            </>
          ) : (
            "Create campaign draft"
          )}
        </button>
      </AdminActionBar>
      <p className="muted">
        Cases are preloaded by an ops/local command, not from this page. Optional metadata filters
        query the case dataset read-only and intersect matching identities with that pool; campaign
        creation moves only preloaded review units. Reviewers are selected afterwards, on the
        campaign page.
      </p>
    </div>
  );
  return sectionToExtract;
}
