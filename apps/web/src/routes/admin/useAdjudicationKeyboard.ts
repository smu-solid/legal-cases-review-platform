import { useEffect } from "react";

import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import { type LocalAdjudicationDecision, verdictOptions } from "./adjudicationDecisionState";

export function useAdjudicationKeyboard({
  activeItem,
  activeDecision,
  editable,
  visibleItems,
  bundle,
  onUpdate,
  onSelect,
  onSave,
  onSubmit,
  onTogglePicking,
  onToggleShortcuts,
  onDismiss,
}: {
  activeItem: AdjudicationWorkspaceItem | null;
  activeDecision: LocalAdjudicationDecision | undefined;
  editable: boolean;
  visibleItems: AdjudicationWorkspaceItem[];
  bundle: AdjudicationCaseWorkspace | undefined;
  onUpdate: (partial: Partial<LocalAdjudicationDecision>) => void;
  onSelect: (itemId: string | null) => void;
  onSave: () => void;
  onSubmit: () => void;
  onTogglePicking: () => void;
  onToggleShortcuts: () => void;
  onDismiss: () => void;
}) {
  useEffect(() => {
    function keyDown(event: KeyboardEvent) {
      const target = event.target instanceof HTMLElement ? event.target : null;
      const typing = Boolean(target?.closest("input, textarea, select, [contenteditable='true']"));
      if (event.isComposing) return;
      if (event.repeat) {
        if (event.key === "Enter" && !typing) event.preventDefault();
        return;
      }
      if (document.querySelector("[role='dialog']")) {
        if (event.key === "Escape") onDismiss();
        if (event.key === "?" && document.getElementById("adjudication-shortcuts-title"))
          onToggleShortcuts();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        onSave();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "Enter" && target?.closest("button, a, summary, [role='button']")) return;
      if (typing && event.key !== "Escape") return;
      const options = activeItem ? verdictOptions(activeItem) : [];
      const number = Number(event.key);
      if (editable && activeDecision && number >= 1 && number <= options.length) {
        const selected = options[number - 1].value;
        onUpdate({
          verdict: selected,
          correctedProvenanceSpans:
            selected === "all_wrong" ? activeDecision.correctedProvenanceSpans : [],
        });
        return;
      }
      const index = activeItem
        ? visibleItems.findIndex((item) => item.item_id === activeItem.item_id)
        : -1;
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        onSelect(visibleItems[Math.min(visibleItems.length - 1, index + 1)]?.item_id ?? null);
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        onSelect(visibleItems[Math.max(0, index - 1)]?.item_id ?? null);
      } else if (event.key === "s") onSave();
      else if (event.key === "Enter") {
        event.preventDefault();
        onSubmit();
      } else if (
        event.key === "m" &&
        editable &&
        activeDecision?.verdict === "all_wrong" &&
        (activeItem?.proposal_item || activeItem?.evidence_window_ids.length)
      )
        onTogglePicking();
      else if (event.key === "?") onToggleShortcuts();
      else if (event.key === "Escape") onDismiss();
      else if (event.key === "g" && bundle && activeItem) {
        const groupIndex = bundle.field_groups.findIndex((group) =>
          group.items.some((item) => item.item_id === activeItem.item_id),
        );
        onSelect(
          bundle.field_groups[(groupIndex + 1) % bundle.field_groups.length]?.items[0]?.item_id ??
            null,
        );
      }
    }
    document.addEventListener("keydown", keyDown);
    return () => document.removeEventListener("keydown", keyDown);
  });
}
