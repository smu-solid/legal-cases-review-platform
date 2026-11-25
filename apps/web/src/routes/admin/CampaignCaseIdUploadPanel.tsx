import type { AppliedCaseIdState } from "./caseSelection/types";
import { useCampaignCaseIdUpload } from "./caseSelection/useCampaignCaseIdUpload";
export type { AppliedCaseIdState } from "./caseSelection/types";

import type { CampaignCaseIdSelection } from "../../api/types";
import { AdminActionBar } from "../../components/admin/AdminLayout";

interface CampaignCaseIdUploadPanelProps {
  tenantId: string;
  sourceFamilies: string[];
  enabled: boolean;
  initialSelection?: CampaignCaseIdSelection | null;
  initialFileName?: string | null;
  showExistingCasesWarning?: boolean;
  onStateChange: (state: AppliedCaseIdState) => void;
}

export function CampaignCaseIdUploadPanel({
  tenantId,
  sourceFamilies,
  enabled,
  initialSelection,
  initialFileName,
  showExistingCasesWarning = false,
  onStateChange,
}: CampaignCaseIdUploadPanelProps) {
  const {
    selection,
    result,
    fileName,
    validationError,
    receiptExpired,
    copied,
    fileInputKey,
    dragActive,
    setDragActive,
    dragDepth,
    applyMutation,
    handleFileChange,
    handleDrop,
    removeFile,
    copyUnmatchedIds,
  } = useCampaignCaseIdUpload({
    sourceFamilies,
    initialSelection,
    initialFileName,
    tenantId,
    enabled,
    onStateChange,
  });

  return (
    <fieldset className="case-filter-panel case-upload-panel" disabled={!enabled}>
      <legend>Upload case IDs</legend>
      <p className="muted case-filter-summary">
        Upload one UTF-8 text file containing one case ID per line. IDs are normalized,
        deduplicated, and matched exactly against cases remaining in the case pool.
      </p>
      {showExistingCasesWarning && selection ? (
        <div className="notice compact" role="note">
          This list applies to future additions. Existing campaign cases remain unchanged.
        </div>
      ) : null}
      <label
        className={`case-upload-dropzone${dragActive ? " is-dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          if (enabled) setDragActive(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragActive(false);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
      >
        <strong>Drag and drop a .txt file here</strong>
        <span>or</span>
        <span className="case-upload-picker">
          <span className="secondary-button">Choose file</span>
          <span className="case-upload-picker-name">{fileName ?? "No file chosen"}</span>
        </span>
        <input
          className="sr-only"
          key={fileInputKey}
          type="file"
          accept=".txt,text/plain"
          onChange={handleFileChange}
        />
      </label>
      {fileName ? (
        <div className="case-upload-file">
          <strong>Selected file</strong>
          <ul>
            <li>
              <span>{fileName}</span>
              <button
                aria-label={`Remove ${fileName}`}
                className="secondary-button"
                type="button"
                onClick={removeFile}
              >
                Remove
              </button>
            </li>
          </ul>
        </div>
      ) : null}
      {applyMutation.isPending ? <p role="status">Checking case IDs against the pool…</p> : null}
      {validationError ? (
        <div className="form-error" role="alert">
          {validationError}
        </div>
      ) : null}
      {applyMutation.isError ? (
        <div className="form-error" role="alert">
          Case IDs could not be checked against the pool. Upload the file again.
        </div>
      ) : null}
      {receiptExpired ? (
        <div className="notice compact" role="alert">
          Uploaded case IDs expired. Upload the file again.
        </div>
      ) : null}
      {result ? (
        <div className="case-upload-results" role="status">
          <p>
            {result.case_id_matching_count} of {result.uploaded_unique_count} unique uploaded case
            IDs match cases remaining in the case pool.
          </p>
          {result.unmatched_case_ids.length > 0 ? (
            <div>
              <label>
                Case IDs not matched in the pool
                <textarea
                  readOnly
                  rows={Math.min(10, result.unmatched_case_ids.length)}
                  value={result.unmatched_case_ids.join("\n")}
                />
              </label>
              <AdminActionBar>
                <button className="secondary-button" type="button" onClick={copyUnmatchedIds}>
                  Copy unmatched case IDs
                </button>
                {copied ? <span role="status">Copied to clipboard.</span> : null}
              </AdminActionBar>
            </div>
          ) : (
            <p className="muted">All uploaded case IDs were matched.</p>
          )}
        </div>
      ) : null}
    </fieldset>
  );
}
