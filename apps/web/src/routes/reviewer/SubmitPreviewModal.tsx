import type { GroupItem } from "../../api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";

export interface PreviewRow {
  item: GroupItem;
  valueCorrect: boolean | null;
  provenanceCorrect: boolean | null;
  correctedValue: string;
  comment: string;
  failureReason: string;
  ready: boolean;
  validationMessage?: string;
  alreadySubmitted: boolean;
  hasUnsavedDraft: boolean;
}

const REASON_LABELS: Record<string, string> = {
  value_incorrect: "Value is incorrect",
  value_incomplete: "Value is incomplete",
  evidence_wrong_location: "Evidence points to the wrong place",
  evidence_not_locatable: "Evidence cannot be located",
  other: "Other",
};

function formatFailureReason(failureReason: string): string {
  return REASON_LABELS[failureReason] ?? failureReason;
}

export interface SubmitPreviewError {
  itemLabel: string;
  message: string;
  isStale: boolean;
}

export function SubmitPreviewModal({
  caseTitle,
  campaignName,
  rows,
  isSubmitting,
  isSavingDrafts,
  error,
  onCancel,
  onSaveAllDrafts,
  onConfirm,
  onRefresh,
}: {
  caseTitle: string;
  campaignName: string | null;
  rows: PreviewRow[];
  isSubmitting: boolean;
  isSavingDrafts: boolean;
  error: SubmitPreviewError | null;
  onCancel: () => void;
  onSaveAllDrafts: () => void;
  onConfirm: () => void;
  onRefresh: () => void;
}) {
  // Fields still needing work before the whole case can be submitted: not yet submitted and not yet
  // ready (a required answer missing). A field that is submitted, or drafted-and-ready, is fine.
  const incompleteCount = rows.filter((row) => !row.alreadySubmitted && !row.ready).length;
  const submittedCount = rows.filter((row) => row.alreadySubmitted).length;
  const unsavedDraftCount = rows.filter((row) => row.hasUnsavedDraft).length;
  const canSubmitCase = rows.length > 0 && incompleteCount === 0;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="modal-panel modal-panel-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="preview-title"
        onClick={(event) => event.stopPropagation()}
      >
        <button type="button" className="modal-close" aria-label="Close" onClick={onCancel}>
          ×
        </button>
        <h3 id="preview-title">Review before you submit this case</h3>
        <p className="preview-case-identity">
          <strong>{caseTitle}</strong>
          {campaignName ? <span className="muted"> · {campaignName}</span> : null}
        </p>
        <p className="muted">
          This is what will be recorded for every field. Use "Back to edit" to change anything
          before confirming.
        </p>
        <ProgressBar value={submittedCount} total={rows.length} label="Fields submitted" />
        <div className="preview-table-wrap">
          <table className="preview-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value correct?</th>
                <th scope="col">Provenance correct?</th>
                <th scope="col">Corrected / proposed value</th>
                <th scope="col">Comment</th>
                <th scope="col">Reason</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.item.review_unit_id}
                  className={
                    !row.alreadySubmitted && !row.ready ? "preview-row-incomplete" : undefined
                  }
                >
                  <td>{row.item.item_label}</td>
                  <td>
                    {row.item.reviewer_proposal || row.valueCorrect === null
                      ? "—"
                      : row.valueCorrect
                        ? "Yes"
                        : "No"}
                  </td>
                  <td>
                    {row.item.reviewer_proposal || row.provenanceCorrect === null
                      ? "—"
                      : row.provenanceCorrect
                        ? "Yes"
                        : "No"}
                  </td>
                  <td>{row.correctedValue || "—"}</td>
                  <td>{row.comment || "—"}</td>
                  <td>{row.failureReason ? formatFailureReason(row.failureReason) : "—"}</td>
                  <td>
                    {row.alreadySubmitted
                      ? "Submitted"
                      : row.validationMessage
                        ? row.validationMessage
                        : row.hasUnsavedDraft
                          ? "Draft (not saved)"
                          : row.ready
                            ? "Ready"
                            : "Incomplete -- required answer missing"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {incompleteCount > 0 ? (
          <div className="notice compact" role="status">
            {incompleteCount} field{incompleteCount === 1 ? "" : "s"} still incomplete. You can
            submit fields individually as you finish them, or go back and finish every field before
            submitting the whole case here.
          </div>
        ) : null}
        {error ? (
          <div className="notice compact" role="alert">
            &ldquo;{error.itemLabel}&rdquo; could not be submitted: {error.message} Fields already
            submitted above stay submitted.
            {error.isStale ? (
              <button type="button" className="link-button" onClick={onRefresh}>
                Refresh and retry
              </button>
            ) : null}
          </div>
        ) : null}
        {canSubmitCase ? (
          <div className="notice compact" role="status">
            Once you submit this case, it is final and cannot be edited again.
          </div>
        ) : null}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onCancel}>
            Back to edit
          </button>
          {}
          {unsavedDraftCount > 0 ? (
            <button
              className="secondary-button"
              type="button"
              disabled={isSavingDrafts || isSubmitting}
              onClick={onSaveAllDrafts}
            >
              {isSavingDrafts ? (
                <>
                  <Spinner /> Saving...
                </>
              ) : (
                "Save all as draft"
              )}
            </button>
          ) : null}
          <button
            className="primary-button"
            type="button"
            disabled={isSubmitting || !canSubmitCase}
            onClick={onConfirm}
          >
            {isSubmitting ? "Submitting..." : "Confirm & submit case"}
          </button>
        </div>
      </div>
    </div>
  );
}
