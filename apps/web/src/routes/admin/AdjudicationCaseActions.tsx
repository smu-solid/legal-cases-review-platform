import type { AdjudicationWorkspaceItem } from "../../api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";
import type { LocalAdjudicationDecision, Verdict } from "./adjudicationDecisionState";

export interface AdjudicationPreviewRow {
  item: AdjudicationWorkspaceItem;
  decision: LocalAdjudicationDecision;
  ready: boolean;
}

export function AdjudicationShortcutsModal({
  options,
  onClose,
}: {
  options: { value: Verdict; label: string }[];
  onClose: () => void;
}) {
  const rows = [
    ["j / k / ↓ / ↑", "Next / previous field"],
    ["g", "Jump to next group"],
    ...options.map((option, index) => [`${index + 1}`, option.label]),
    ["m", "Mark corrected provenance (All wrong only)"],
    ["s / Cmd+S / Ctrl+S", "Save draft"],
    ["Enter", "Submit field"],
    ["?", "Open / close this help"],
    ["Esc", "Close dialog / cancel provenance marking"],
  ];
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adjudication-shortcuts-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="adjudication-shortcuts-title">Keyboard shortcuts</h3>
        <table className="shortcuts-table">
          <tbody>
            {rows.map(([keys, action]) => (
              <tr key={keys}>
                <td>
                  <kbd>{keys}</kbd>
                </td>
                <td>{action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export function AdjudicationSubmitPreviewModal({
  caseTitle,
  campaignName,
  rows,
  busy,
  error,
  onCancel,
  onSaveAll,
  onConfirm,
}: {
  caseTitle: string;
  campaignName: string;
  rows: AdjudicationPreviewRow[];
  busy: "saving" | "submitting" | null;
  error: string | null;
  onCancel: () => void;
  onSaveAll: () => void;
  onConfirm: () => void;
}) {
  const submitted = rows.filter((row) => row.decision.submitted).length;
  const incomplete = rows.filter((row) => !row.decision.submitted && !row.ready).length;
  const unsaved = rows.some((row) => !row.decision.submitted && row.decision.dirty);
  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="modal-panel modal-panel-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adjudication-preview-title"
        onClick={(event) => event.stopPropagation()}
      >
        <button type="button" className="modal-close" aria-label="Close" onClick={onCancel}>
          ×
        </button>
        <h3 id="adjudication-preview-title">Review before you submit this case</h3>
        <p className="preview-case-identity">
          <strong>{caseTitle}</strong>
          <span className="muted"> · {campaignName}</span>
        </p>
        <p className="muted">
          This is what will be recorded for every adjudication field. Submitted fields are final and
          read-only.
        </p>
        <ProgressBar value={submitted} total={rows.length} label="Adjudications submitted" />
        <div className="preview-table-wrap">
          <table className="preview-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Final decision</th>
                <th scope="col">Final / corrected value</th>
                <th scope="col">Note</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.item.review_unit_id}
                  className={
                    !row.decision.submitted && !row.ready ? "preview-row-incomplete" : undefined
                  }
                >
                  <td>{row.item.item_label}</td>
                  <td>
                    {!row.decision.verdict
                      ? "—"
                      : row.decision.verdict.startsWith("preferred:") ||
                          row.decision.verdict.startsWith("proposal:")
                        ? row.item.proposal_item?.proposals.find(
                            (p) => row.decision.verdict === `proposal:${p.id}`,
                          )
                          ? `${row.item.proposal_item.proposals.find((p) => row.decision.verdict === `proposal:${p.id}`)!.reviewer_label} · Proposal ${row.item.proposal_item.proposals.find((p) => row.decision.verdict === `proposal:${p.id}`)!.proposal_number} preferred`
                          : "Reviewer preferred"
                        : row.decision.verdict.replaceAll("_", " ")}
                  </td>
                  <td>
                    {row.decision.correctedValue ||
                      row.item.proposal_item?.final_value ||
                      row.item.proposal_item?.proposals.find(
                        (p) => row.decision.verdict === `proposal:${p.id}`,
                      )?.value ||
                      "—"}
                  </td>
                  <td>{row.decision.comment || "—"}</td>
                  <td>
                    {row.decision.submitted
                      ? "Submitted"
                      : row.ready
                        ? row.decision.dirty
                          ? "Draft (not saved)"
                          : "Ready"
                        : row.decision.verdict
                          ? row.item.proposal_item
                            ? "Incomplete — check decision, note and provenance"
                            : "Incomplete — required note missing"
                          : "Incomplete — final decision missing"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {incomplete ? (
          <div className="notice compact" role="status">
            {incomplete} field{incomplete === 1 ? " is" : "s are"} incomplete.
          </div>
        ) : null}
        {error ? (
          <div className="notice compact" role="alert">
            {error} Fields already submitted remain submitted.
          </div>
        ) : null}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onCancel}>
            Back to edit
          </button>
          {unsaved ? (
            <button
              className="secondary-button"
              type="button"
              disabled={busy !== null}
              onClick={onSaveAll}
            >
              {busy === "saving" ? (
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
            disabled={busy !== null || incomplete > 0 || rows.length === 0}
            onClick={onConfirm}
          >
            {busy === "submitting" ? "Submitting..." : "Confirm & submit case"}
          </button>
        </div>
      </div>
    </div>
  );
}
