import type { AdjudicationWorkspaceItem } from "../../api/types";
import type { LocalAdjudicationDecision } from "./adjudicationDecisionState";

export function AdjudicationDraftRecovery({
  items,
  drafts,
  active,
  onRestore,
  onRefresh,
  onReassess,
}: {
  items: AdjudicationWorkspaceItem[];
  drafts: Record<string, LocalAdjudicationDecision>;
  active: AdjudicationWorkspaceItem | null;
  onRestore: (id: string) => void;
  onRefresh: () => void;
  onReassess: () => void;
}) {
  const missing = Object.entries(drafts).filter(
    ([id, d]) => d.dirty && !items.some((i) => i.item_id === id),
  );
  const local = active ? drafts[active.item_id] : undefined;
  const stale =
    local?.dirty &&
    (active?.proposal_item
      ? local.proposalVersion !== active.proposal_item.lock_version
      : local.membershipVersion !== (active?.membership_version ?? 0));
  return (
    <div>
      <button type="button" className="link-button" onClick={onRefresh}>
        Refresh workspace (keep unsaved input)
      </button>
      {stale ? (
        <div className="notice" role="alert">
          Membership or saved state changed. Your input is retained; review the current proposals
          before retrying.
          <button type="button" onClick={onReassess}>
            I have reassessed this item — use my input
          </button>
        </div>
      ) : null}
      {missing.map(([id, draft]) => (
        <section className="notice" key={id}>
          <h4>Retained draft from a changed item</h4>
          <textarea
            readOnly
            aria-label="Retained adjudication draft"
            value={JSON.stringify(draft, null, 2)}
          />
          <button
            type="button"
            disabled={!active || active.participation_status !== "pending"}
            onClick={() => onRestore(id)}
          >
            Use this draft for the selected item
          </button>
        </section>
      ))}
    </div>
  );
}
