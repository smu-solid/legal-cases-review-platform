import { useCallback, useEffect, useState } from "react";

import type { CampaignCaseFilter, CampaignCaseIdSelection } from "../../api/types";
import { CampaignCaseFilterPanel, type AppliedCaseFilterState } from "./CampaignCaseFilterPanel";
import { CampaignCaseIdUploadPanel, type AppliedCaseIdState } from "./CampaignCaseIdUploadPanel";

export type CampaignCaseSelectionMode = "filter" | "upload";

export interface AppliedCaseSelectionState {
  mode: CampaignCaseSelectionMode;
  caseFilter: CampaignCaseFilter;
  filterResult: AppliedCaseFilterState["result"];
  caseIdSelection: CampaignCaseIdSelection | null;
  caseIdFileName: string | null;
  caseIdResult: AppliedCaseIdState["result"];
  ready: boolean;
  sourceSignature: string;
}

interface CampaignCaseSelectionPanelProps {
  tenantId: string;
  sourceFamilies?: string[];
  csrfToken: string | null;
  enabled: boolean;
  initialFilter?: CampaignCaseFilter | null;
  initialCaseIdSelection?: CampaignCaseIdSelection | null;
  initialCaseIdFileName?: string | null;
  showExistingCasesWarning?: boolean;
  onStateChange: (state: AppliedCaseSelectionState) => void;
}

const emptyFilterState: AppliedCaseFilterState = {
  caseFilter: { version: "v1", all: [] },
  result: null,
  draftChanged: true,
  receiptExpired: false,
  ready: false,
  sourceSignature: "",
};

const emptyUploadState: AppliedCaseIdState = {
  caseIdSelection: null,
  fileName: null,
  result: null,
  ready: false,
  sourceSignature: "",
};

const allCaseFamilies: string[] = [];

export function CampaignCaseSelectionPanel({
  tenantId,
  sourceFamilies = allCaseFamilies,
  csrfToken,
  enabled,
  initialFilter,
  initialCaseIdSelection,
  initialCaseIdFileName,
  showExistingCasesWarning = false,
  onStateChange,
}: CampaignCaseSelectionPanelProps) {
  const [mode, setMode] = useState<CampaignCaseSelectionMode>(
    initialCaseIdSelection ? "upload" : "filter",
  );
  const [filterState, setFilterState] = useState(emptyFilterState);
  const [uploadState, setUploadState] = useState(emptyUploadState);
  const handleFilterState = useCallback(
    (state: AppliedCaseFilterState) => setFilterState(state),
    [],
  );
  const handleUploadState = useCallback((state: AppliedCaseIdState) => setUploadState(state), []);

  useEffect(() => {
    const active = mode === "filter" ? filterState : uploadState;
    onStateChange({
      mode,
      caseFilter: filterState.caseFilter,
      filterResult: filterState.result,
      caseIdSelection: uploadState.caseIdSelection,
      caseIdFileName: uploadState.fileName,
      caseIdResult: uploadState.result,
      ready: active.ready,
      sourceSignature: active.sourceSignature,
    });
  }, [filterState, mode, onStateChange, uploadState]);

  return (
    <div className={`case-selection-panel${enabled ? "" : " is-disabled"}`}>
      <div className="case-selection-tabs" role="tablist" aria-label="Case selection method">
        <button
          className={mode === "filter" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={mode === "filter"}
          disabled={!enabled}
          onClick={() => setMode("filter")}
        >
          Filter
        </button>
        <button
          className={mode === "upload" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={mode === "upload"}
          disabled={!enabled}
          onClick={() => setMode("upload")}
        >
          Upload case IDs
        </button>
      </div>
      <div role="tabpanel" hidden={mode !== "filter"}>
        <CampaignCaseFilterPanel
          tenantId={tenantId}
          sourceFamilies={sourceFamilies}
          csrfToken={csrfToken}
          enabled={enabled && mode === "filter"}
          initialFilter={initialFilter}
          showExistingCasesWarning={showExistingCasesWarning}
          onStateChange={handleFilterState}
        />
      </div>
      <div role="tabpanel" hidden={mode !== "upload"}>
        <CampaignCaseIdUploadPanel
          tenantId={tenantId}
          sourceFamilies={sourceFamilies}
          enabled={enabled && mode === "upload"}
          initialSelection={initialCaseIdSelection}
          initialFileName={initialCaseIdFileName}
          showExistingCasesWarning={showExistingCasesWarning}
          onStateChange={handleUploadState}
        />
      </div>
    </div>
  );
}
