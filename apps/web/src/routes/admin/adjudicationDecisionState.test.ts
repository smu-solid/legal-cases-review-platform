import { describe, expect, it } from "vitest";

import type { AdjudicationWorkspaceItem } from "../../api/types";
import {
  adjudicationDecisionReady,
  adjudicationDraftReady,
  buildAdjudicationDecision,
  buildAdjudicationDraft,
  hydrateAdjudicationDecision,
} from "./adjudicationDecisionState";

describe("adjudication decision state", () => {
  const readyItem = {
    item_id: "field-1",
    evidence_window_ids: ["evidence-1"],
    submissions: [{ submission_id: "submission-1" }, { submission_id: "submission-2" }],
    required_reviews: 2,
    membership_version: 3,
    participation_status: "pending",
  } as unknown as AdjudicationWorkspaceItem;

  it("builds a note-only draft without inventing a verdict or reviewer assessments", () => {
    const local = {
      ...hydrateAdjudicationDecision(readyItem, "source"),
      comment: "Private work in progress",
      dirty: true,
    };
    expect(adjudicationDraftReady(readyItem, local)).toBe(true);
    expect(buildAdjudicationDraft(readyItem, local)).toMatchObject({
      outcome: null,
      comment: "Private work in progress",
      membership_version: 3,
      reviewer_assessments: [],
      preferred_submission_id: null,
    });
    expect(adjudicationDecisionReady(readyItem, local)).toBe(false);
    expect(() => buildAdjudicationDecision(readyItem, local)).toThrow(
      "A final adjudication decision is required.",
    );
  });

  it("reloads a saved draft with no verdict and preserves the private note", () => {
    const item = {
      ...readyItem,
      draft: { decision: { outcome: null, comment: "Saved before verdict" } },
    } as unknown as AdjudicationWorkspaceItem;
    const local = hydrateAdjudicationDecision(item, "source");
    expect(local).toMatchObject({
      verdict: null,
      comment: "Saved before verdict",
      saved: true,
      dirty: false,
      submitted: false,
    });
    expect(adjudicationDraftReady(item, local)).toBe(false);
    expect(adjudicationDecisionReady(item, local)).toBe(false);
  });

  it.each(["all_wrong", "unsupported_or_not_locatable", "exceptional_skip"] as const)(
    "retains the final comment requirement for %s",
    (verdict) => {
      const local = { ...hydrateAdjudicationDecision(readyItem, "source"), verdict };
      expect(adjudicationDecisionReady(readyItem, local)).toBe(false);
      expect(adjudicationDecisionReady(readyItem, { ...local, comment: "Reason" })).toBe(true);
    },
  );

  it("retains proposal draft requirements when only a note has changed", () => {
    const item = { ...readyItem, proposal_item: {} } as AdjudicationWorkspaceItem;
    const local = { ...hydrateAdjudicationDecision(readyItem, "source"), dirty: true };
    expect(adjudicationDraftReady(item, local)).toBe(false);
  });

  it("starts a new adjudication field without a selected final decision", () => {
    const item = {
      evidence_window_ids: [],
      submissions: [],
      participation_status: "pending",
    } as unknown as AdjudicationWorkspaceItem;
    const local = hydrateAdjudicationDecision(item, "source");
    expect(local.verdict).toBeNull();
    expect(adjudicationDecisionReady(item, local)).toBe(false);
  });

  it("hydrates and serializes corrected provenance without selected display text", () => {
    const item = {
      evidence_window_ids: ["evidence-1"],
      submissions: [],
      submitted_decision: {
        outcome: "all_wrong",
        comment: "Correction",
        corrected_provenance_spans: [
          { evidence_window_id: "evidence-1", char_start: 1, char_end: 4 },
        ],
      },
      participation_status: "submitted",
    } as unknown as AdjudicationWorkspaceItem;
    const local = hydrateAdjudicationDecision(item, "abcdef");
    expect(local.correctedProvenanceSpans[0].selected_text).toBe("bcd");
    expect(buildAdjudicationDecision(item, local).corrected_provenance_spans).toEqual([
      { evidence_window_id: "evidence-1", char_start: 1, char_end: 4, note: null },
    ]);
  });
});
