import type { ReviewerGroupingBundle } from "../../api/types";
import type { LocalAnswer } from "./reviewerAnswerState";

// Only compare positions in the displayed source. The context projection also supports legacy
// snippet renders; raw evidence offsets can belong to another document or representation.
export function orderCitations(
  bundle: ReviewerGroupingBundle | undefined,
  answers: Record<string, LocalAnswer>,
): ReviewerGroupingBundle | undefined {
  if (!bundle) return bundle;
  const snapshot = bundle.source_render.source_snapshot_id;
  const verified = new Set([snapshot, ...(bundle.proposal_source_snapshot_ids ?? [])]);
  const version = bundle.proposal_source_version;
  const valid = (span: { char_start: number; char_end: number }) =>
    span.char_start >= 0 &&
    span.char_start < span.char_end &&
    span.char_end <= bundle.source_render.content.length;
  return {
    ...bundle,
    field_groups: bundle.field_groups.map((group) => {
      if (group.group_id !== "cited_cases") return group;
      const positioned = group.items.map((item, index) => {
        const answer = answers[item.review_unit_id];
        const summary = item.answer_summary;
        const context = (bundle.provenance_context ?? []).filter(
          (c) =>
            c.item_id === item.review_unit_id &&
            c.source_snapshot_id === snapshot &&
            c.source_version === version &&
            valid(c),
        );
        const superseded = answer
          ? answer.provenance_correct === false || Boolean(answer.corrected_provenance_spans.length)
          : summary?.provenance_correct === false ||
            Boolean(summary?.corrected_provenance_spans.length);
        const authored =
          answer?.corrected_provenance_spans ??
          summary?.corrected_provenance_spans ??
          item.reviewer_proposal?.provenance ??
          [];
        const spans = authored.filter(
          (s) =>
            verified.has(s.source_snapshot_id ?? "") && s.source_version === version && valid(s),
        );
        const saved = context.filter((c) => c.kind !== "Extracted");
        const originals = context.filter((c) => c.kind === "Extracted" && !c.superseded);
        const hasCorrection = superseded || Boolean(spans.length) || (!answer && saved.length > 0);
        let positions: { char_start: number }[] = originals;
        if (item.reviewer_proposal) positions = spans;
        else if (hasCorrection) {
          positions = spans;
          if ((!answer || answer.saved) && !spans.length) positions = saved;
        }
        let starts = positions.map((s) => s.char_start);
        if (!hasCorrection && !item.reviewer_proposal) {
          starts = [...starts];
          if (!starts.length && !item.source_anchor_unavailable_reason) {
            const anchor = bundle.source_render.anchors.find(
              (a) => a.anchor_id === item.source_anchor_id,
            );
            if (
              anchor?.char_start != null &&
              anchor.char_end != null &&
              valid({ char_start: anchor.char_start, char_end: anchor.char_end })
            )
              starts.push(anchor.char_start);
          }
        }
        return { item, index, position: starts.length ? Math.min(...starts) : Infinity };
      });
      positioned.sort((a, b) => a.position - b.position || a.index - b.index);
      return { ...group, items: positioned.map(({ item }) => item) };
    }),
  };
}
