import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { GroupItem, ReviewerGroupingBundle } from "../../api/types";
import {
  WorkspaceSourcePane,
  type WorkspaceSourceView as SourceView,
} from "../../components/WorkspaceSourcePane";
import type { LocalAnswer } from "./reviewerAnswerState";
import { reviewerContext } from "./reviewerProvenanceContext";
export function CaseFooterNav({
  tenantId,
  campaignId,
  prevAssignmentId,
  nextAssignmentId,
  isLeaving,
  onLeave,
}: {
  tenantId: string;
  campaignId: string | null;
  prevAssignmentId: string | null;
  nextAssignmentId: string | null;
  isLeaving: boolean;
  onLeave: (to: string) => void;
}) {
  const taskHref = (assignmentId: string) =>
    `/t/${tenantId}/review/task/${assignmentId}${campaignId ? `?campaignId=${campaignId}` : ""}`;
  const queueHref = campaignId
    ? `/t/${tenantId}/review/campaigns/${campaignId}`
    : `/t/${tenantId}/review`;

  // Previous/Next are buttons, not plain links: an unsaved edit on the current case is auto-saved as
  // a draft before we leave (see `leaveTo` in the workspace), so moving between cases mid-review
  // never silently drops the reviewer's in-progress answer. "Go to campaign queue" stays a link (a
  // safe escape hatch) but also routes through the same guard.
  return (
    <nav className="case-footer-nav" aria-label="Case navigation">
      <button
        type="button"
        className="secondary-button"
        disabled={!prevAssignmentId || isLeaving}
        onClick={() => prevAssignmentId && onLeave(taskHref(prevAssignmentId))}
      >
        ← Previous case
      </button>
      <Link
        className="secondary-button"
        to={queueHref}
        onClick={(event) => {
          event.preventDefault();
          onLeave(queueHref);
        }}
      >
        Go to campaign queue
      </Link>
      <button
        type="button"
        className="secondary-button"
        disabled={!nextAssignmentId || isLeaving}
        onClick={() => nextAssignmentId && onLeave(taskHref(nextAssignmentId))}
      >
        Next case →
      </button>
    </nav>
  );
}

// Exported for direct unit-testing of the Text-mode rendering/scroll behaviour without mounting
// the full workspace page (which needs router, query-client, and auth-session providers).
export function SourcePane({
  bundle,
  activeItem,
  activeAnswer,
  answers = {},
  onOpenItem,
  artifactAnchorUnavailable,
  documentHtml,
  htmlLoading,
  view,
  onViewChange,
  pickingProvenance,
  onProvenancePick,
  onAddCitation,
  addingCitationDisabled = false,
  activeGroupId,
  preserveScroll = false,
}: {
  onAddCitation?: (charStart: number, charEnd: number) => void;
  addingCitationDisabled?: boolean;
  activeGroupId?: string;
  preserveScroll?: boolean;
  bundle: ReviewerGroupingBundle;
  activeItem: GroupItem | null;
  activeAnswer: LocalAnswer | undefined;
  answers?: Record<string, LocalAnswer>;
  onOpenItem?: (id: string) => void;
  artifactAnchorUnavailable: boolean;
  documentHtml: string | null;
  htmlLoading: boolean;
  view: SourceView;
  onViewChange: (view: SourceView) => void;
  pickingProvenance: boolean;
  onProvenancePick: (charStart: number, charEnd: number) => void;
}) {
  const inCitedCases = Boolean(
    activeGroupId === "cited_cases" ||
    (activeItem &&
      bundle.field_groups.some(
        (g) =>
          g.group_id === "cited_cases" &&
          g.items.some((i) => i.review_unit_id === activeItem.review_unit_id),
      )),
  );
  const [showCitations, setShowCitations] = useState(false);
  useEffect(() => {
    setShowCitations(false);
  }, [inCitedCases, bundle.source_render.source_snapshot_id]);
  const showing = inCitedCases && showCitations;
  const context =
    inCitedCases && !showing ? [] : reviewerContext(bundle, activeItem, answers, showing);
  const showLegend = showing || (!inCitedCases && Boolean(activeItem?.reviewer_proposal));
  const canAdd =
    inCitedCases &&
    !bundle.case_submitted &&
    !addingCitationDisabled &&
    Boolean(
      bundle.proposal_source_version &&
      bundle.field_groups.find((g) => g.group_id === "cited_cases")?.add_item_label,
    );
  return (
    <WorkspaceSourcePane
      preserveScroll={preserveScroll}
      headingControls={
        <button
          type="button"
          role="switch"
          aria-checked={showing}
          disabled={!inCitedCases}
          onClick={() => setShowCitations((value) => !value)}
          className="citation-visibility-toggle source-expand-toggle"
        >
          <span className="citation-toggle-track" aria-hidden="true" />
          Show all citations
        </button>
      }
      onAddCitation={canAdd ? onAddCitation : undefined}
      contextMarks={
        activeItem?.reviewer_proposal
          ? context.filter((mark) => mark.itemId !== activeItem.review_unit_id)
          : context
      }
      tooltipPrefix={activeItem?.reviewer_proposal || showing ? "Provenance for" : undefined}
      contextLegend={
        showLegend ? <ProvenanceContextLegend marks={context} onOpen={onOpenItem} /> : undefined
      }
      caseTitle={bundle.case_header.case_title}
      sourceRender={bundle.source_render}
      activeItem={activeItem}
      authoredItem={Boolean(activeItem?.reviewer_proposal)}
      correctedProvenanceSpans={(activeAnswer?.corrected_provenance_spans ?? []).map((span) => ({
        ...span,
        ...(activeItem?.reviewer_proposal
          ? {
              ownerKey: activeItem.review_unit_id,
              ownerLabel: `${activeAnswer?.corrected_value.trim() || "New item (value not entered)"} — Your added item`,
            }
          : {}),
      }))}
      artifactAnchorUnavailable={artifactAnchorUnavailable}
      documentHtml={documentHtml}
      htmlLoading={htmlLoading}
      view={view}
      onViewChange={onViewChange}
      pickingProvenance={pickingProvenance}
      onProvenancePick={onProvenancePick}
    />
  );
}

export function ProvenanceContextLegend({
  marks,
  onOpen,
}: {
  marks: ReturnType<typeof reviewerContext>;
  onOpen?: (id: string) => void;
}) {
  const items = [...new Map(marks.map((m) => [m.ownerKey, m])).values()];
  return (
    <div className="provenance-context-legend">
      <p>
        <span className="source-highlight">Yellow: extracted</span>
        {" · "}
        <span className="source-highlight-selected">Blue: your corrections and additions</span>
        {" · "}
        <span className="source-highlight source-highlight-superseded">
          Faded yellow: incorrect or superseded
        </span>
        {" · Double-underlined: current item's marks"}
      </p>
      <details>
        <summary>Items highlighted in this group ({items.length})</summary>
        <ul>
          {items.map((m) => (
            <li key={m.ownerKey}>
              {m.ownerLabel}{" "}
              {onOpen && (
                <button type="button" className="link-button" onClick={() => onOpen(m.itemId)}>
                  Open existing item
                </button>
              )}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
