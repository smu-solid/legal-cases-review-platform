import type { ProposalSpan } from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import {
  WorkspaceSourcePane,
  type DisplayProvenanceSpan,
  type WorkspaceSourceView,
} from "../../components/WorkspaceSourcePane";
import { adjudicationReviewerLabel } from "./adjudicationReviewerLabel";

export function AdjudicationSourcePane({
  focusedProposalSpan,
  caseTitle,
  sourceRender,
  activeItem,
  documentHtml,
  htmlLoading,
  artifactAnchorUnavailable,
  view,
  onViewChange,
  adjudicatorSpans,
  adjudicatorLabel,
  pickingProvenance,
  onProvenancePick,
}: {
  focusedProposalSpan?: (ProposalSpan & { label: string }) | null;
  caseTitle: string;
  sourceRender: AdjudicationCaseWorkspace["source_render"];
  activeItem: AdjudicationWorkspaceItem | null;
  documentHtml: string | null;
  htmlLoading: boolean;
  artifactAnchorUnavailable: boolean;
  view: WorkspaceSourceView;
  onViewChange: (view: WorkspaceSourceView) => void;
  adjudicatorSpans: DisplayProvenanceSpan[];
  adjudicatorLabel: string;
  pickingProvenance: boolean;
  onProvenancePick: (charStart: number, charEnd: number) => void;
}) {
  const reviewerSpans =
    activeItem?.submissions.flatMap((submission) =>
      (submission.corrected_provenance_spans ?? []).map((span) => ({
        ...span,
        ownerKey: submission.submission_id,
        ownerLabel: adjudicationReviewerLabel(submission),
      })),
    ) ?? [];
  const validSpan = (span: ProposalSpan) =>
    (span.source_snapshot_id === activeItem?.proposal_source?.snapshotId ||
      Boolean(activeItem?.proposal_source?.snapshotIds?.includes(span.source_snapshot_id))) &&
    span.source_version === activeItem?.proposal_source?.version &&
    span.char_start >= 0 &&
    span.char_end <= sourceRender.content.length;
  reviewerSpans.push(
    ...(activeItem?.proposal_item?.proposals ?? []).flatMap((p) =>
      (p.provenance ?? []).filter(validSpan).map((s) => ({
        evidence_window_id: p.id,
        char_start: s.char_start,
        char_end: s.char_end,
        ownerKey: p.id,
        ownerLabel: `${p.reviewer_label} · Proposal ${p.proposal_number}`,
      })),
    ),
  );
  const first = activeItem?.proposal_item?.proposals[0]?.provenance?.[0];
  const requested = focusedProposalSpan ?? first;
  const navigation = requested && validSpan(requested) ? requested : null;
  const anchorId = navigation ? `proposal-${navigation.char_start}-${navigation.char_end}` : null;
  const render = navigation
    ? {
        ...sourceRender,
        anchors: [
          ...sourceRender.anchors,
          {
            anchor_id: anchorId!,
            char_start: navigation.char_start,
            char_end: navigation.char_end,
            scroll_hint: "center" as const,
          },
        ],
      }
    : sourceRender;
  const ownedAdjudicatorSpans = adjudicatorSpans.map((span) => ({
    ...span,
    ownerKey: "current-adjudicator",
    ownerLabel: adjudicatorLabel,
  }));
  return (
    <WorkspaceSourcePane
      className="adjudication-source-pane"
      caseTitle={caseTitle}
      sourceRender={render}
      activeItem={
        anchorId && activeItem ? { ...activeItem, source_anchor_id: anchorId } : activeItem
      }
      authoredItem={Boolean(
        activeItem?.proposal_item && !activeItem.proposal_item.extracted_adjudication_id,
      )}
      correctedProvenanceSpans={reviewerSpans}
      adjudicatorProvenanceSpans={ownedAdjudicatorSpans}
      documentHtml={documentHtml}
      htmlLoading={htmlLoading}
      artifactAnchorUnavailable={artifactAnchorUnavailable}
      view={view}
      onViewChange={onViewChange}
      pickingProvenance={pickingProvenance}
      onProvenancePick={onProvenancePick}
    />
  );
}
