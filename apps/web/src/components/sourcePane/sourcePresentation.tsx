import type { ReactNode } from "react";
import type { CorrectedProvenanceSpan, ReviewerGroupingBundle } from "../../api/types";
import type { EvidenceWindow } from "../groundedIn";

export type WorkspaceSourceView = "document" | "text";

export type DisplayProvenanceSpan = CorrectedProvenanceSpan & {
  selected_text?: string;
  ownerKey?: string;
  ownerLabel?: string;
};

export type SourceRender = ReviewerGroupingBundle["source_render"];

export type ActiveSourceItem = {
  review_unit_id: string;
  source_anchor_id?: string | null;
  source_anchor_unavailable_reason?: string | null;
  evidence_windows?: EvidenceWindow[] | null;
} | null;

export type SourceMark = {
  key: string;
  char_start: number;
  char_end: number;
  className: string;
  ownerKey?: string;
  ownerLabel?: string;
  ownerKind?: "reviewer" | "adjudicator";
};

export function renderMarkedSource(
  content: string,
  marks: SourceMark[],
  showPointerTooltip: (text: string, x: number, y: number) => void,
  showFocusTooltip: (text: string, element: HTMLElement) => void,
  hideTooltip: () => void,
  tooltipPrefix: string,
) {
  const clamped = marks
    .map((mark) => ({
      ...mark,
      char_start: Math.max(0, Math.min(mark.char_start, content.length)),
      char_end: Math.max(0, Math.min(mark.char_end, content.length)),
    }))
    .filter((mark) => mark.char_end > mark.char_start);
  if (!clamped.length) return [content];

  const boundaries = Array.from(
    new Set(clamped.flatMap((mark) => [mark.char_start, mark.char_end])),
  ).sort((a, b) => a - b);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  boundaries.forEach((point) => {
    if (point <= cursor) return;
    const active = clamped.filter((mark) => mark.char_start <= cursor && mark.char_end >= point);
    const text = content.slice(cursor, point);
    if (active.length) {
      const activeAnchor = active.some((mark) => mark.key === "proposed");
      const reviewerOwners = new Set(
        active
          .filter((mark) => mark.ownerKind === "reviewer")
          .map((mark) => mark.ownerKey ?? mark.key),
      );
      const classes = new Set(active.map((mark) => mark.className));
      if (reviewerOwners.size > 1) classes.add("source-highlight-reviewer-overlap");
      const ownerLabels = Array.from(
        new Map(
          active
            .filter((mark) => mark.ownerLabel)
            .map((mark) => [mark.ownerKey ?? mark.key, mark.ownerLabel as string]),
        ).values(),
      );
      const tooltipText = ownerLabels.length
        ? `${tooltipPrefix ? `${tooltipPrefix}: ` : ""}${ownerLabels.join(", ")}`
        : null;
      nodes.push(
        <mark
          className={Array.from(classes).join(" ")}
          key={`${active.map((mark) => mark.key).join("+")}-${cursor}`}
          data-active-anchor={activeAnchor ? "true" : undefined}
          data-highlight-owners={tooltipText ?? undefined}
          tabIndex={tooltipText ? 0 : undefined}
          aria-label={tooltipText ? `${text}. ${tooltipText}` : undefined}
          onMouseEnter={(event) =>
            tooltipText && showPointerTooltip(tooltipText, event.clientX, event.clientY)
          }
          onMouseMove={(event) =>
            tooltipText && showPointerTooltip(tooltipText, event.clientX, event.clientY)
          }
          onMouseLeave={hideTooltip}
          onFocus={(event) => tooltipText && showFocusTooltip(tooltipText, event.currentTarget)}
          onClick={(event) => {
            if (tooltipText && !window.getSelection()?.toString())
              showFocusTooltip(tooltipText, event.currentTarget);
          }}
          onBlur={hideTooltip}
        >
          {text}
        </mark>,
      );
    } else nodes.push(text);
    cursor = point;
  });
  if (cursor < content.length) nodes.push(content.slice(cursor));
  return nodes;
}

export function buildSourceMarks({
  contextMarks,
  activeAnchor,
  correctedProvenanceSpans,
  authoredItem,
  contextLegend,
  adjudicatorProvenanceSpans,
}: {
  contextMarks: SourceMark[];
  activeItem: ActiveSourceItem;
  activeAnchor: SourceRender["anchors"][number] | null;
  correctedProvenanceSpans: DisplayProvenanceSpan[];
  authoredItem: boolean;
  contextLegend: ReactNode;
  adjudicatorProvenanceSpans: DisplayProvenanceSpan[];
}) {
  const marks: SourceMark[] = [...contextMarks];
  if (activeAnchor?.char_start != null && activeAnchor.char_end != null) {
    marks.push({
      key: "proposed",
      char_start: activeAnchor.char_start,
      char_end: activeAnchor.char_end,
      className: "source-highlight",
    });
  }
  correctedProvenanceSpans.forEach((span, index) =>
    marks.push({
      key: authoredItem && index === 0 ? "proposed" : `corrected-${index}`,
      char_start: span.char_start,
      char_end: span.char_end,
      className: `source-highlight-selected${contextLegend ? " source-highlight-current" : ""}`,
      ownerKey: span.ownerKey,
      ownerLabel: span.ownerLabel,
      ownerKind: "reviewer",
    }),
  );
  adjudicatorProvenanceSpans.forEach((span, index) =>
    marks.push({
      key: `adjudicator-corrected-${index}`,
      char_start: span.char_start,
      char_end: span.char_end,
      className: "source-highlight-adjudicator",
      ownerKey: span.ownerKey,
      ownerLabel: span.ownerLabel,
      ownerKind: "adjudicator",
    }),
  );
  return { marks };
}
