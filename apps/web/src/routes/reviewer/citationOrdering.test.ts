import { describe, expect, it } from "vitest";
import { syntheticBundle } from "../../test/fixtures/reviewer";
import { orderCitations } from "./citationOrdering";
import { emptyAnswer } from "./reviewerAnswerState";
import { newProposal, projectProposals } from "./reviewerProposals";

const group = syntheticBundle.field_groups.find((g) => g.group_id === "cited_cases")!;
const [a, b] = group.items;
const version = "a".repeat(64);
const snapshot = syntheticBundle.source_render.source_snapshot_id;
const context = (id: string, start: number) => ({
  item_id: id,
  group_id: "cited_cases",
  value: id,
  kind: "Extracted" as const,
  superseded: false,
  source_snapshot_id: snapshot,
  source_version: version,
  char_start: start,
  char_end: start + 3,
});
const bundle = {
  ...syntheticBundle,
  proposal_source_version: version,
  field_groups: [
    { ...group, items: [a, b, { ...a, review_unit_id: "unlocated", source_anchor_id: null }] },
  ],
  provenance_context: [
    context(a.review_unit_id, 80),
    context(b.review_unit_id, 20),
    context(a.review_unit_id, 10),
  ],
};
const ids = (result: ReturnType<typeof orderCitations>) =>
  result!.field_groups[0].items.map((i) => i.review_unit_id);
const span = (start: number) => ({
  evidence_window_id: "window",
  source_snapshot_id: snapshot,
  source_version: version,
  char_start: start,
  char_end: start + 3,
});

describe("citation appearance order", () => {
  it("uses the earliest recorded occurrence, handles untouched answers and leaves unknown locations last", () => {
    expect(ids(orderCitations(bundle, { [a.review_unit_id]: emptyAnswer }))).toEqual([
      a.review_unit_id,
      b.review_unit_id,
      "unlocated",
    ]);
    expect(bundle.field_groups[0].items.map((i) => i.review_unit_id)).toEqual([
      a.review_unit_id,
      b.review_unit_id,
      "unlocated",
    ]);
  });
  it("inserts a selected-text draft before saving and uses its edited provenance immediately", () => {
    const proposal = newProposal(group);
    const projected = projectProposals(bundle, [proposal], "assignment");
    expect(
      ids(
        orderCitations(projected, {
          [proposal.id]: { ...emptyAnswer, corrected_provenance_spans: [span(15)] },
        }),
      ),
    ).toEqual([a.review_unit_id, proposal.id, b.review_unit_id, "unlocated"]);
    expect(
      ids(
        orderCitations(projected, {
          [proposal.id]: { ...emptyAnswer, corrected_provenance_spans: [span(5)] },
        }),
      )[0],
    ).toBe(proposal.id);
  });
  it("prefers corrections, excludes stale/foreign spans, and does not reuse cleared provenance", () => {
    expect(
      ids(
        orderCitations(bundle, {
          [a.review_unit_id]: {
            ...emptyAnswer,
            provenance_correct: false,
            corrected_provenance_spans: [span(50)],
          },
        }),
      )[0],
    ).toBe(b.review_unit_id);
    const corrected = {
      ...emptyAnswer,
      provenance_correct: false,
      corrected_provenance_spans: [{ ...span(0), source_snapshot_id: "foreign" }],
    };
    expect(ids(orderCitations(bundle, { [a.review_unit_id]: corrected }))).toEqual([
      b.review_unit_id,
      a.review_unit_id,
      "unlocated",
    ]);
    const proposal = { ...newProposal(group), provenance: [span(1)] };
    const projected = projectProposals(bundle, [proposal], "assignment");
    expect(ids(orderCitations(projected, { [proposal.id]: emptyAnswer })).at(-1)).toBe(proposal.id);
  });
  it("keeps ties stable and preserves other groups", () => {
    const tied = {
      ...bundle,
      field_groups: [...syntheticBundle.field_groups.slice(0, 1), bundle.field_groups[0]],
      provenance_context: [context(a.review_unit_id, 10), context(b.review_unit_id, 10)],
    };
    const result = orderCitations(tied, {})!;
    expect(result.field_groups[0]).toBe(tied.field_groups[0]);
    expect(result.field_groups[1].items.map((i) => i.review_unit_id)).toEqual([
      a.review_unit_id,
      b.review_unit_id,
      "unlocated",
    ]);
  });
});
