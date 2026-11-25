import type { FilterField } from "./caseSelection/caseFilterDraft";
import type { AppliedCaseFilterState } from "./caseSelection/types";
import { useCampaignCaseFilter } from "./caseSelection/useCampaignCaseFilter";
export type { AppliedCaseFilterState } from "./caseSelection/types";

import type { CampaignCaseFilter } from "../../api/types";
import { AdminActionBar } from "../../components/admin/AdminLayout";

interface CampaignCaseFilterPanelProps {
  tenantId: string;
  sourceFamilies: string[];
  csrfToken: string | null;
  enabled: boolean;
  initialFilter?: CampaignCaseFilter | null;
  showExistingCasesWarning?: boolean;
  onStateChange: (state: AppliedCaseFilterState) => void;
}

export function CampaignCaseFilterPanel({
  tenantId,
  sourceFamilies,
  csrfToken,
  enabled,
  initialFilter,
  showExistingCasesWarning = false,
  onStateChange,
}: CampaignCaseFilterPanelProps) {
  const {
    filterRows,
    setFilterRows,
    appliedResult,
    validationError,
    receiptExpired,
    setDismissedSuggestionQuery,
    debouncedSubjectQuery,
    draftChanged,
    emptyDraft,
    ready,
    applyMutation,
    applyFilters,
    correctionQuery,
    exportMutation,
  } = useCampaignCaseFilter({
    initialFilter,
    sourceFamilies,
    tenantId,
    enabled,
    onStateChange,
    csrfToken,
  });

  return (
    <fieldset className="case-filter-panel" disabled={!enabled}>
      <legend>Filter cases (optional)</legend>
      <p className="muted case-filter-summary">
        The case dataset is queried read-only. Matching case IDs are then limited to the case pool.
        Multiple filters are matched together.
      </p>
      {showExistingCasesWarning && filterRows.length > 0 ? (
        <div className="notice compact" role="note">
          This filter applies to future additions. Existing campaign cases remain unchanged and may
          not satisfy the filter.
        </div>
      ) : null}
      <div className="case-filter-clauses">
        {filterRows.map((row) => {
          const suggestions = correctionQuery.data?.suggestions ?? [];
          return (
            <div className="case-filter-clause" key={row.id}>
              <label>
                Field
                <select
                  value={row.field}
                  onChange={(event) => {
                    const field = event.target.value as FilterField;
                    setFilterRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, field, value: "" } : item,
                      ),
                    );
                  }}
                >
                  <option
                    value="case_subject"
                    disabled={filterRows.some(
                      (item) => item.id !== row.id && item.field === "case_subject",
                    )}
                  >
                    Case subject
                  </option>
                  <option
                    value="judgment_year"
                    disabled={filterRows.some(
                      (item) => item.id !== row.id && item.field === "judgment_year",
                    )}
                  >
                    Judgment year
                  </option>
                </select>
              </label>
              <label>
                Operator
                <select disabled value={row.field === "case_subject" ? "contains" : "is any of"}>
                  <option>{row.field === "case_subject" ? "contains" : "is any of"}</option>
                </select>
              </label>
              <label className="case-filter-value">
                Value
                <input
                  placeholder={
                    row.field === "case_subject" ? "e.g. Criminal" : "e.g. 2010, 2014, 2016-2019"
                  }
                  value={row.value}
                  onChange={(event) => {
                    const value = event.target.value;
                    setDismissedSuggestionQuery("");
                    setFilterRows((current) =>
                      current.map((item) => (item.id === row.id ? { ...item, value } : item)),
                    );
                  }}
                />
                {row.field === "judgment_year" ? (
                  <small>One year, comma-separated years, or inclusive ranges (1965–2026).</small>
                ) : null}
              </label>
              <button
                className="secondary-button case-filter-remove"
                type="button"
                onClick={() =>
                  setFilterRows((current) => current.filter((item) => item.id !== row.id))
                }
              >
                Remove
              </button>
              {row.field === "case_subject" &&
              suggestions.length > 0 &&
              debouncedSubjectQuery === row.value.trim() ? (
                <div className="notice compact case-filter-suggestion">
                  <span>Did you mean:</span>
                  <AdminActionBar>
                    {suggestions.map((suggestion) => (
                      <button
                        className="secondary-button"
                        key={suggestion.value}
                        type="button"
                        onClick={() =>
                          setFilterRows((current) =>
                            current.map((item) =>
                              item.id === row.id ? { ...item, value: suggestion.value } : item,
                            ),
                          )
                        }
                      >
                        “{suggestion.value}” ({suggestion.matching_pool_cases_count})
                      </button>
                    ))}
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => setDismissedSuggestionQuery(debouncedSubjectQuery)}
                    >
                      Dismiss
                    </button>
                  </AdminActionBar>
                </div>
              ) : null}
              {row.field === "case_subject" && correctionQuery.isFetching ? (
                <p className="muted case-filter-suggestion" role="status">
                  Checking spelling…
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      <AdminActionBar>
        {filterRows.length < 2 ? (
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              const field: FilterField = filterRows.some((row) => row.field === "case_subject")
                ? "judgment_year"
                : "case_subject";
              setFilterRows((current) => [
                ...current,
                { id: crypto.randomUUID(), field, value: "" },
              ]);
            }}
          >
            Add filter
          </button>
        ) : null}
        <button
          className="primary-button"
          type="button"
          disabled={emptyDraft || (!draftChanged && !receiptExpired) || applyMutation.isPending}
          onClick={applyFilters}
        >
          {applyMutation.isPending ? "Applying…" : "Apply filters"}
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={
            !ready || appliedResult?.case_filter_matching_count === 0 || exportMutation.isPending
          }
          onClick={() => exportMutation.mutate()}
        >
          {exportMutation.isPending ? "Exporting…" : "Export case IDs"}
        </button>
      </AdminActionBar>
      {validationError ? <div className="form-error">{validationError}</div> : null}
      {applyMutation.isError ? (
        <div className="form-error" role="alert">
          Case filters could not be applied. Check the values and try again.
        </div>
      ) : null}
      {exportMutation.isError ? (
        <div className="form-error" role="alert">
          Case IDs could not be exported. Check the case pool or reapply the filters.
        </div>
      ) : null}
      {enabled && !emptyDraft && draftChanged && !applyMutation.isPending ? (
        <p className="notice compact" role="status">
          Filters changed — apply to update matching cases.
        </p>
      ) : null}
      {enabled && receiptExpired ? (
        <p className="notice compact" role="alert">
          Applied filter expired — apply filters again.
        </p>
      ) : null}
      {ready && appliedResult ? (
        <p className="muted" role="status">
          {appliedResult.case_filter_matching_count} cases in the pool match this filter.
        </p>
      ) : null}
    </fieldset>
  );
}
