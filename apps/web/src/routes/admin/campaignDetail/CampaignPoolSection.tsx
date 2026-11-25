import {
  AdminActionBar,
  AdminFormGrid,
  AdminMetricGrid,
  AdminSectionCard,
} from "../../../components/admin/AdminLayout";
import { Spinner } from "../../../components/Spinner";
import { loadCasesErrorMessage } from "../campaignDetailFormatters";
import type { useCampaignControls } from "./useCampaignDetail";
import { useCampaignPool } from "./useCampaignPool";

export function CampaignPoolSection({
  loadCasesMutation,
  loadCasesResult,
  loadCaseCountMode,
  setLoadCaseCountMode,
  loadCaseCount,
  setLoadCaseCount,
  editing,
  currentCaseCount,
  displayedSourcePoolCaseCount,
  displayedFilterMatchingCount,
  displayedEligibleCaseCount,
  displayedProjectedCaseCount,
  loadInfeasible,
  loadAvailability,
  loadNeedsConfirmation,
  loadFilterReady,
  plannedCasesToAdd,
}: {
  loadCasesMutation: ReturnType<typeof useCampaignPool>["loadCasesMutation"];
  loadCasesResult: ReturnType<typeof useCampaignControls>["loadCasesResult"];
  loadCaseCountMode: ReturnType<typeof useCampaignControls>["loadCaseCountMode"];
  setLoadCaseCountMode: ReturnType<typeof useCampaignControls>["setLoadCaseCountMode"];
  loadCaseCount: ReturnType<typeof useCampaignControls>["loadCaseCount"];
  setLoadCaseCount: ReturnType<typeof useCampaignControls>["setLoadCaseCount"];
  editing: ReturnType<typeof useCampaignControls>["editing"];
  currentCaseCount: ReturnType<typeof useCampaignPool>["currentCaseCount"];
  displayedSourcePoolCaseCount: ReturnType<typeof useCampaignPool>["displayedSourcePoolCaseCount"];
  displayedFilterMatchingCount: ReturnType<typeof useCampaignPool>["displayedFilterMatchingCount"];
  displayedEligibleCaseCount: ReturnType<typeof useCampaignPool>["displayedEligibleCaseCount"];
  displayedProjectedCaseCount: ReturnType<typeof useCampaignPool>["displayedProjectedCaseCount"];
  loadInfeasible: ReturnType<typeof useCampaignPool>["loadInfeasible"];
  loadAvailability: ReturnType<typeof useCampaignPool>["loadAvailability"];
  loadNeedsConfirmation: ReturnType<typeof useCampaignPool>["loadNeedsConfirmation"];
  loadFilterReady: ReturnType<typeof useCampaignPool>["loadFilterReady"];
  plannedCasesToAdd: ReturnType<typeof useCampaignPool>["plannedCasesToAdd"];
}) {
  const sectionToExtract = (
    <AdminSectionCard
      eyebrow="Cases"
      title="Add cases from preloaded pool"
      titleId="load-cases-title"
      summary={
        <>
          Add already-preloaded eligible cases to this campaign. The counts below show what the
          campaign has now, what remains available in the pool, and the total after this add.
        </>
      }
    >
      {loadCasesMutation.isError ? (
        <div className="form-error" role="alert">
          {loadCasesErrorMessage(loadCasesMutation.error)}
        </div>
      ) : null}
      {loadCasesResult && !loadCasesResult.not_ready_for_publish ? (
        <div className="notice compact" role="status">
          Added {loadCasesResult.materialized_cases} case
          {loadCasesResult.materialized_cases === 1 ? "" : "s"} (
          {loadCasesResult.materialized_units} review unit
          {loadCasesResult.materialized_units === 1 ? "" : "s"}).
        </div>
      ) : null}
      <AdminFormGrid>
        <label>
          Cases to add
          <select
            value={loadCaseCountMode}
            onChange={(event) => setLoadCaseCountMode(event.target.value as "all" | "count")}
          >
            <option value="all">All currently available cases</option>
            <option value="count">Exact number to add</option>
          </select>
        </label>
        {loadCaseCountMode === "count" ? (
          <label>
            Number of new cases to add
            <input
              type="number"
              min={1}
              value={loadCaseCount}
              onChange={(event) => setLoadCaseCount(Number(event.target.value) || 0)}
            />
          </label>
        ) : null}
      </AdminFormGrid>
      <p className="muted">
        Fields and optional case filters come from Edit campaign. Save campaign changes before
        adding cases. Reviewers are unaffected: select them separately below, starting from 0.
      </p>
      {editing ? (
        <div className="notice compact" role="status">
          Finish or cancel the campaign edit before adding cases.
        </div>
      ) : null}
      <AdminMetricGrid>
        <div className="metric-card">
          <span>Current campaign</span>
          <strong>{currentCaseCount} cases</strong>
        </div>
        <div className="metric-card">
          <span>Available in pool</span>
          <strong>
            {displayedSourcePoolCaseCount === null
              ? "Calculating…"
              : `${displayedSourcePoolCaseCount} cases`}
          </strong>
        </div>
        <div className="metric-card">
          <span>Matches case selection</span>
          <strong>
            {displayedFilterMatchingCount === null
              ? "Calculating…"
              : `${displayedFilterMatchingCount} cases`}
          </strong>
        </div>
        <div className="metric-card">
          <span>Eligible to add</span>
          <strong>
            {displayedEligibleCaseCount === null
              ? "Calculating…"
              : `${displayedEligibleCaseCount} cases`}
          </strong>
        </div>
        <div className="metric-card">
          <span>After this add</span>
          <strong>
            {displayedProjectedCaseCount === null
              ? "Calculating…"
              : `${displayedProjectedCaseCount} cases`}
          </strong>
        </div>
      </AdminMetricGrid>
      {loadInfeasible && loadAvailability ? (
        <div className="form-error" role="alert">
          {loadAvailability.infeasible_message ??
            "No new cases or fields are available for this campaign scope."}
          {loadAvailability.fields_fully_exhausted.length ? (
            <> Exhausted field groups: {loadAvailability.fields_fully_exhausted.join(", ")}.</>
          ) : null}
        </div>
      ) : null}
      {loadNeedsConfirmation && loadAvailability ? (
        <div className="notice compact" role="alert">
          {loadAvailability.infeasible_message ??
            `Only ${loadAvailability.eligible_cases_count} eligible cases are available.`}
          <AdminActionBar>
            <button
              className="primary-button"
              disabled={editing || loadCasesMutation.isPending || !loadFilterReady}
              type="button"
              onClick={() => loadCasesMutation.mutate(true)}
            >
              Load {loadAvailability.eligible_cases_count} case
              {loadAvailability.eligible_cases_count === 1 ? "" : "s"}
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setLoadCaseCountMode("all")}
            >
              Cancel
            </button>
          </AdminActionBar>
        </div>
      ) : !loadInfeasible ? (
        <AdminActionBar>
          <button
            className="primary-button"
            disabled={
              editing || loadCasesMutation.isPending || !loadFilterReady || !loadAvailability
            }
            type="button"
            onClick={() => loadCasesMutation.mutate(false)}
          >
            {loadCasesMutation.isPending ? (
              <>
                <Spinner /> Loading…
              </>
            ) : (
              `Add ${plannedCasesToAdd} case${plannedCasesToAdd === 1 ? "" : "s"}`
            )}
          </button>
        </AdminActionBar>
      ) : null}
    </AdminSectionCard>
  );
  return sectionToExtract;
}
