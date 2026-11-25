import type { ReactNode } from "react";
import { evidenceLocationNotice } from "./groundedIn";
import { InfoTooltip } from "./InfoTooltip";
import { resolveProvenancePick } from "./provenancePick";
import { SafeSourceFrame } from "./SafeSourceFrame";
import { SelectionCitationAction } from "./SelectionCitationAction";
import type {
  ActiveSourceItem,
  DisplayProvenanceSpan,
  SourceMark,
  SourceRender,
  WorkspaceSourceView,
} from "./sourcePane/sourcePresentation";
import { buildSourceMarks, renderMarkedSource } from "./sourcePane/sourcePresentation";
import { useSourceViewport } from "./sourcePane/useSourceViewport";
import { Spinner } from "./Spinner";

export type {
  DisplayProvenanceSpan,
  SourceMark,
  WorkspaceSourceView,
} from "./sourcePane/sourcePresentation";

export function WorkspaceSourcePane({
  caseTitle,
  sourceRender,
  activeItem,
  correctedProvenanceSpans = [],
  adjudicatorProvenanceSpans = [],
  documentHtml,
  htmlLoading,
  artifactAnchorUnavailable,
  view,
  onViewChange,
  pickingProvenance = false,
  authoredItem = false,
  onProvenancePick,
  className,
  contextMarks = [],
  tooltipPrefix = "Highlighted by",
  contextLegend,
  headingControls,
  onAddCitation,
  preserveScroll = false,
}: {
  headingControls?: ReactNode;
  onAddCitation?: (charStart: number, charEnd: number) => void;
  preserveScroll?: boolean;
  contextMarks?: SourceMark[];
  tooltipPrefix?: string;
  contextLegend?: ReactNode;
  caseTitle: string;
  sourceRender: SourceRender;
  activeItem: ActiveSourceItem;
  correctedProvenanceSpans?: DisplayProvenanceSpan[];
  adjudicatorProvenanceSpans?: DisplayProvenanceSpan[];
  documentHtml: string | null;
  htmlLoading: boolean;
  artifactAnchorUnavailable: boolean;
  view: WorkspaceSourceView;
  onViewChange: (view: WorkspaceSourceView) => void;
  pickingProvenance?: boolean;
  authoredItem?: boolean;
  onProvenancePick?: (charStart: number, charEnd: number) => void;
  className?: string;
}) {
  const activeAnchor = activeItem?.source_anchor_id
    ? (sourceRender.anchors.find((anchor) => anchor.anchor_id === activeItem.source_anchor_id) ??
      null)
    : null;
  const anchorMissing =
    activeItem &&
    (!activeItem.source_anchor_id || activeItem.source_anchor_unavailable_reason || !activeAnchor);
  const locationNotice = anchorMissing
    ? evidenceLocationNotice(
        activeItem?.source_anchor_unavailable_reason,
        activeItem?.evidence_windows ?? null,
      )
    : null;
  const hasDocument = Boolean(documentHtml);
  const showDocument = view === "document" && hasDocument;
  const {
    sourceTextRef,
    isExpanded,
    setIsExpanded,
    ownerTooltip,
    setOwnerTooltip,
    showPointerTooltip,
    showFocusTooltip,
  } = useSourceViewport({ activeItem, showDocument, preserveScroll, sourceRender });
  const { marks } = buildSourceMarks({
    contextMarks,
    activeItem,
    activeAnchor,
    correctedProvenanceSpans,
    authoredItem,
    contextLegend,
    adjudicatorProvenanceSpans,
  });

  function handleMouseUp() {
    setOwnerTooltip(null);
    if (!pickingProvenance || !onProvenancePick) return;
    const root = sourceTextRef.current;
    const selection = window.getSelection();
    if (!root || !selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return;
    const picked = resolveProvenancePick(root, range);
    selection.removeAllRanges();
    if (picked) onProvenancePick(picked.charStart, picked.charEnd);
  }

  return (
    <aside
      className={`${className ? `${className} ` : ""}source-pane${isExpanded ? " is-expanded" : ""}`}
      aria-labelledby="source-title"
    >
      <div className="pane-heading">
        <div className="source-heading-row">
          <h3 id="source-title">Judgment</h3>
          <InfoTooltip
            label="About the judgment"
            text="The judgment stays as imported. Reviewers' corrections and supporting evidence are stored separately."
          />
        </div>
        <div className="pane-heading-actions">
          {headingControls}
          {hasDocument ? (
            <div className="segmented-control" role="group" aria-label="Source view mode">
              <button
                type="button"
                aria-pressed={view === "document"}
                className={view === "document" ? "is-selected" : ""}
                onClick={() => onViewChange("document")}
              >
                Document
              </button>
              <button
                type="button"
                aria-pressed={view === "text"}
                className={view === "text" ? "is-selected" : ""}
                onClick={() => onViewChange("text")}
              >
                Text
              </button>
            </div>
          ) : (
            <span className="status-chip">{sourceRender.render_mode}</span>
          )}
          <button
            type="button"
            className="source-expand-toggle"
            aria-pressed={isExpanded}
            aria-label={isExpanded ? "Collapse source view" : "Expand source view to full screen"}
            title={isExpanded ? "Collapse source view" : "Expand source view"}
            onClick={() => setIsExpanded((current) => !current)}
          >
            {isExpanded ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>
      <div className="source-body">
        {contextLegend}
        {!showDocument && locationNotice && !authoredItem ? (
          <div
            className="notice compact"
            role="status"
            data-evidence-location={locationNotice.kind}
          >
            {locationNotice.message}
            {locationNotice.recordedIn ? (
              <>
                {" "}
                <span className="evidence-location-source">
                  Recorded in {locationNotice.recordedIn}.
                </span>
              </>
            ) : null}
          </div>
        ) : null}
        {htmlLoading ? (
          <div className="notice compact" role="status">
            <Spinner /> Loading the sanitized source document...
          </div>
        ) : null}
        {hasDocument && artifactAnchorUnavailable ? (
          <div className="notice compact" role="status">
            Artifact anchor map unavailable. Text fallback anchors remain available.
          </div>
        ) : null}
        {!showDocument && pickingProvenance ? (
          <div className="notice notice-info compact" role="status">
            Selecting evidence — select the correct text below, then release the mouse. Press Esc to
            cancel.
          </div>
        ) : null}
        {showDocument ? (
          <SafeSourceFrame
            html={documentHtml as string}
            title={`Sanitized source document for ${caseTitle}`}
          />
        ) : (
          <pre
            ref={sourceTextRef}
            className={pickingProvenance ? "source-text is-picking" : "source-text"}
            tabIndex={0}
            onMouseUp={handleMouseUp}
          >
            {renderMarkedSource(
              sourceRender.content,
              marks,
              showPointerTooltip,
              showFocusTooltip,
              () => setOwnerTooltip(null),
              tooltipPrefix,
            )}
          </pre>
        )}
      </div>
      <SelectionCitationAction
        root={sourceTextRef}
        enabled={!showDocument && !pickingProvenance && Boolean(onAddCitation)}
        onAdd={onAddCitation}
        resetKey={`${activeItem?.review_unit_id}:${sourceRender.source_snapshot_id}`}
      />
      {ownerTooltip ? (
        <div
          className={`source-highlight-owner-tooltip${ownerTooltip.above ? " is-above" : ""}`}
          role="tooltip"
          style={{ left: ownerTooltip.left, top: ownerTooltip.top }}
        >
          {ownerTooltip.text}
        </div>
      ) : null}
    </aside>
  );
}
