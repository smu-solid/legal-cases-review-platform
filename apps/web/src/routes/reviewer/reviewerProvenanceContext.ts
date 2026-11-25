import type { GroupItem, ReviewerGroupingBundle } from "../../api/types";
import type { SourceMark } from "../../components/WorkspaceSourcePane";
import type { LocalAnswer } from "./reviewerAnswerState";

export function reviewerContext(
  bundle: ReviewerGroupingBundle,
  active: GroupItem | null,
  answers: Record<string, LocalAnswer>,
  showCitations = false,
) {
  const group = bundle.field_groups.find((g) =>
    showCitations
      ? g.group_id === "cited_cases"
      : Boolean(active?.reviewer_proposal && g.group_id === active.reviewer_proposal.group_id),
  );
  if (!group) return [];
  const verified = new Set([
    bundle.source_render.source_snapshot_id,
    ...(bundle.proposal_source_snapshot_ids ?? []),
  ]);
  return group.items
    .filter((i) => showCitations || i.review_unit_id !== active?.review_unit_id)
    .flatMap((item) => {
      const answer = answers[item.review_unit_id];
      const marks = (bundle.provenance_context ?? []).filter(
        (c) =>
          c.item_id === item.review_unit_id &&
          c.source_snapshot_id === bundle.source_render.source_snapshot_id &&
          c.source_version === bundle.proposal_source_version,
      );

      const originals = marks
        .filter((c) => c.kind === "Extracted")
        .map((c) => ({
          ...c,
          superseded: answer
            ? answer.provenance_correct === false ||
              Boolean(answer.corrected_provenance_spans.length)
            : c.superseded,
        }));
      const saved = marks.filter((c) => c.kind !== "Extracted");
      const local = answer?.corrected_provenance_spans
        .filter(
          (s) =>
            verified.has(s.source_snapshot_id ?? "") &&
            s.source_version === bundle.proposal_source_version,
        )
        .map((s) => ({
          ...s,
          item_id: item.review_unit_id,
          group_id: group.group_id,
          value: answer.corrected_value || item.extracted_value_display,
          kind: item.reviewer_proposal ? "Your added item" : "Your correction",
          superseded: false,
        }));
      return [
        ...originals,
        ...(answer && !answer.saved ? (local ?? []) : saved.length ? saved : (local ?? [])),
      ].map(
        (c) =>
          ({
            key: `${c.item_id}:${c.kind}:${c.char_start}:${c.char_end}`,
            itemId: c.item_id,
            char_start: c.char_start,
            char_end: c.char_end,
            className:
              c.kind === "Extracted"
                ? c.superseded
                  ? "source-highlight source-highlight-superseded"
                  : "source-highlight"
                : "source-highlight-selected",
            ownerKey: `${c.item_id}:${c.kind}`,
            ownerLabel: `${c.value} — ${c.kind}${c.superseded ? " (incorrect or superseded provenance)" : ""}`,
          }) satisfies SourceMark & { itemId: string },
      );
    });
}
