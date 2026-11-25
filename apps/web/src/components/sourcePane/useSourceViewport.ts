import { useEffect, useRef, useState } from "react";
import type { ActiveSourceItem, SourceRender } from "./sourcePresentation";

type OwnerTooltip = {
  text: string;
  left: number;
  top: number;
  above: boolean;
};

export function useSourceViewport({
  activeItem,
  showDocument,
  preserveScroll,
  sourceRender,
}: {
  activeItem: ActiveSourceItem;
  showDocument: boolean;
  preserveScroll: boolean;
  sourceRender: SourceRender;
}) {
  const sourceTextRef = useRef<HTMLPreElement | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [ownerTooltip, setOwnerTooltip] = useState<OwnerTooltip | null>(null);

  function tooltipLeft(x: number) {
    const width = Math.min(420, window.innerWidth - 24);
    return Math.max(12, Math.min(x + 16, window.innerWidth - width - 12));
  }

  function showPointerTooltip(text: string, x: number, y: number) {
    setOwnerTooltip({ text, left: tooltipLeft(x), top: y > 140 ? y - 14 : y + 18, above: y > 140 });
  }

  function showFocusTooltip(text: string, element: HTMLElement) {
    const rect = element.getBoundingClientRect();
    const above = rect.top > 140;
    setOwnerTooltip({
      text,
      left: tooltipLeft(rect.left),
      top: above ? rect.top - 14 : rect.bottom + 14,
      above,
    });
  }

  useEffect(() => {
    if (showDocument || preserveScroll) return;
    const container = sourceTextRef.current;
    const node = container?.querySelector<HTMLElement>('[data-active-anchor="true"]');
    if (!container || !node) return;
    const containerRect = container.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    const delta =
      nodeRect.top - containerRect.top - container.clientHeight / 2 + nodeRect.height / 2;
    container.scrollTo({ top: container.scrollTop + delta, behavior: "smooth" });
  }, [
    activeItem?.review_unit_id,
    activeItem?.source_anchor_id,
    sourceRender.content,
    showDocument,
    preserveScroll,
  ]);

  useEffect(() => {
    if (!isExpanded) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsExpanded(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isExpanded]);
  return {
    sourceTextRef,
    isExpanded,
    setIsExpanded,
    ownerTooltip,
    setOwnerTooltip,
    showPointerTooltip,
    showFocusTooltip,
  };
}
