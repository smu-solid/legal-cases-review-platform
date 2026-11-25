import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";

import type { AdjudicationCampaignCaseItem, AdjudicationCaseNeighbors } from "../../api/types";

export function useAdjudicationFooter({
  tenantId,
  campaignId,
  neighbors,
  completed,
  saving,
  setFooterSlot,
  onMove,
}: {
  tenantId: string;
  campaignId: string;
  neighbors: AdjudicationCaseNeighbors | undefined;
  completed: boolean;
  saving: boolean;
  setFooterSlot: (slot: ReactNode) => void;
  onMove: (target: AdjudicationCampaignCaseItem | null | undefined) => void;
}) {
  useEffect(() => {
    const previous = neighbors?.previous_open;
    const next = neighbors?.next_open;
    setFooterSlot(
      <div className="case-footer-nav adjudication-footer-nav">
        <button
          className="secondary-button"
          type="button"
          disabled={!previous || saving}
          onClick={() => onMove(previous)}
        >
          ← Previous case
        </button>
        <Link
          className={completed && !next ? "primary-button" : "secondary-button"}
          to={`/t/${tenantId}/adjudication/campaigns/${campaignId}`}
        >
          Campaign cases
        </Link>
        <button
          className={completed && next ? "primary-button" : "secondary-button"}
          type="button"
          disabled={!next || saving}
          onClick={() => onMove(next)}
        >
          Next case →
        </button>
      </div>,
    );
    return () => setFooterSlot(null);
  }, [campaignId, completed, neighbors, onMove, saving, setFooterSlot, tenantId]);
}
