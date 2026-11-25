import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MembershipChange } from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";

export function ProposalMembershipControls({
  item,
  bundle,
  onChange,
}: {
  item: AdjudicationWorkspaceItem;
  bundle: AdjudicationCaseWorkspace;
  onChange: (body: MembershipChange) => Promise<void>;
}) {
  const [mode, setMode] = useState<"combine" | "separate" | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const working = useRef(false);
  const snapshot = useRef({ version: 0, targets: [] as AdjudicationWorkspaceItem[] });
  const proposal = item.proposal_item!;
  const targets =
    bundle.field_groups
      .find((g) => g.group_id === proposal.group_id)
      ?.items.filter(
        (i) =>
          i.item_id !== item.item_id &&
          i.participation_status === "pending" &&
          !(
            proposal.extracted_adjudication_id &&
            (!i.proposal_item || i.proposal_item.extracted_adjudication_id)
          ),
      ) ?? [];
  async function confirm() {
    if (!mode || working.current) return;
    const selected = snapshot.current.targets.find((i) => i.item_id === target);
    if (mode === "combine" && !selected) return;
    working.current = true;
    setBusy(true);
    setError(false);
    try {
      await onChange({
        action: mode,
        item_id: proposal.id,
        expected_version: snapshot.current.version,
        target_item_id: mode === "combine" ? (selected?.proposal_item?.id ?? null) : null,
        target_version: selected?.proposal_item?.lock_version ?? null,
        target_extracted_id:
          mode === "combine" && !selected?.proposal_item ? selected?.adjudication_id : null,
        target_membership_version: selected?.membership_version ?? 0,
        confirm: true,
      });
      setMode(null);
    } catch {
      setError(true);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  if (proposal.state === "submitted") return null;
  return (
    <div>
      <button
        type="button"
        className="secondary-button"
        onClick={() => {
          snapshot.current = { version: proposal.lock_version, targets };
          setMode("combine");
          setTarget("");
          setError(false);
        }}
      >
        Combine with another item
      </button>
      {proposal.proposals.length > 1 || proposal.extracted_adjudication_id ? (
        <button
          type="button"
          className="secondary-button"
          onClick={() => {
            snapshot.current = { version: proposal.lock_version, targets };
            setMode("separate");
            setError(false);
          }}
        >
          Keep separate
        </button>
      ) : null}
      {mode
        ? createPortal(
            <div className="modal-backdrop">
              <section
                className="modal-panel proposal-membership-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="membership-title"
                onKeyDown={(e) => {
                  if (e.key === "Escape" && !busy) {
                    e.stopPropagation();
                    setMode(null);
                  }
                }}
              >
                <h3 id="membership-title">
                  {mode === "combine" ? "Combine duplicate items" : "Keep proposals separate"}
                </h3>
                {mode === "combine" ? (
                  <label>
                    Combine with
                    <select value={target} onChange={(e) => setTarget(e.target.value)}>
                      <option value="">Select the same cited case/item</option>
                      {targets.map((i) => (
                        <option key={i.item_id} value={i.item_id}>
                          {i.proposal_item?.proposals.map((p) => p.value).join(" / ") ||
                            i.extracted_value_display}{" "}
                          · {i.proposal_item ? "reviewer-added" : "extracted"}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <p>
                  {mode === "combine"
                    ? "Confirm that these entries represent the same cited case/item. Combining does not accept a value."
                    : "Each proposal will require its own decision. The original extracted item, if present, keeps its reviewer submissions."}
                </p>
                <p>
                  Affected saved and unsaved adjudication drafts will be cleared. You must reassess
                  the resulting items. Original reviewer submissions are preserved.
                </p>
                {error ? (
                  <p role="alert">
                    The change was rejected. Your input is retained. Refresh to check for a
                    submitted or changed item.
                  </p>
                ) : null}
                <div className="modal-actions">
                  <button type="button" disabled={busy} onClick={() => setMode(null)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busy || (mode === "combine" && !target)}
                    onClick={() => void confirm()}
                  >
                    {busy
                      ? "Updating…"
                      : mode === "combine"
                        ? "Confirm & combine"
                        : "Confirm separation"}
                  </button>
                </div>
              </section>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
