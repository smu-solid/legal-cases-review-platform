import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AdjudicationProposalCards,
  AdjudicationProposalPreferences,
  type AdjudicationProposalCardEntry,
} from "./AdjudicationProposalCards";

const source = { snapshotId: "snapshot", version: "a".repeat(64), content: "first second third" };
const entries: AdjudicationProposalCardEntry[] = [
  { id: "one", reviewer: "Reviewer A", number: 1, start: 0, end: 5 },
  { id: "two", reviewer: "Reviewer A", number: 2, start: 6, end: 12 },
  { id: "three", reviewer: "Reviewer B", number: 1, start: 13, end: 18 },
].map((value) => ({
  reviewerKey: value.reviewer,
  reviewerLabel: value.reviewer,
  proposalNumber: value.number,
  proposal: {
    id: value.id,
    group_id: "cited_cases",
    value_schema: "cited_case_text/v1",
    original_value: value.id,
    value: `Citation ${value.id}`,
    note: `Note ${value.id}`,
    state: "submitted",
    lock_version: 2,
    created_at: "2026-09-15T00:00:00Z",
    provenance: [
      {
        source_snapshot_id: source.snapshotId,
        source_version: source.version,
        char_start: value.start,
        char_end: value.end,
      },
    ],
  },
}));

describe("adjudication proposal cards", () => {
  it("uses one card per reviewer and keeps proposals numbered without correctness questions", () => {
    render(<AdjudicationProposalCards entries={entries} source={source} onNavigate={vi.fn()} />);
    expect(screen.getAllByRole("article")).toHaveLength(2);
    const reviewerA = screen.getByRole("article", { name: "Reviewer A proposals" });
    expect(within(reviewerA).getByRole("heading", { name: "Proposal 1" })).toBeVisible();
    expect(within(reviewerA).getByRole("heading", { name: "Proposal 2" })).toBeVisible();
    expect(screen.getByText("Citation two")).toBeVisible();
    expect(screen.getByText("Note two")).toBeVisible();
    expect(screen.queryByText(/value correct|provenance correct|extracted value/i)).toBeNull();
  });

  it("navigates to the exact proposal's coordinates with its reviewer and number", () => {
    const navigate = vi.fn();
    render(<AdjudicationProposalCards entries={entries} source={source} onNavigate={navigate} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Reviewer A · Proposal 2 · passage 1 provenance",
      }),
    );
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      entries[1].proposal.provenance?.[0],
      "Reviewer A · Proposal 2 · passage 1",
    );
  });

  it("does not navigate a proposal against a different source version", () => {
    const navigate = vi.fn();
    render(
      <AdjudicationProposalCards
        entries={entries}
        source={{ ...source, version: "b".repeat(64) }}
        onNavigate={navigate}
      />,
    );
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    expect(navigate).not.toHaveBeenCalled();
  });

  it("selects an exact proposal ID and displays its value alongside the option", () => {
    const select = vi.fn();
    render(
      <AdjudicationProposalPreferences
        entries={entries}
        selectedId={null}
        disabled={false}
        onSelect={select}
      />,
    );
    fireEvent.click(
      screen.getByRole("radio", {
        name: "Reviewer A · Proposal 2 preferred Citation two",
      }),
    );
    expect(select).toHaveBeenCalledExactlyOnceWith("two");
  });
});

it("shows a passage from a server-verified field snapshot of the same document", () => {
  render(
    <AdjudicationProposalCards
      entries={entries}
      source={{
        ...source,
        snapshotId: "other-field",
        snapshotIds: [source.snapshotId, "other-field"],
      }}
      onNavigate={vi.fn()}
    />,
  );
  expect(screen.getByText("“first”")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Reviewer A · Proposal 1 · passage 1 provenance" }),
  ).toBeEnabled();
});

it("highlights overlapping provenance from both reviewers across verified field snapshots", async () => {
  const { AdjudicationSourcePane } = await import("./AdjudicationSourcePane");
  const item = {
    review_unit_id: "item",
    evidence_window_ids: [],
    submissions: [],
    proposal_source: {
      snapshotId: "other-field",
      snapshotIds: [source.snapshotId, "other-field"],
      version: source.version,
    },
    proposal_item: {
      extracted_adjudication_id: null,
      proposals: [entries[0], entries[2]].map((entry) => ({
        ...entry.proposal,
        reviewer_label: entry.reviewerLabel,
        reviewer_key: entry.reviewerKey,
        proposal_number: 1,
        provenance: [entries[0].proposal.provenance![0]],
      })),
    },
  } as unknown as import("../../api/types").AdjudicationWorkspaceItem;
  const { container } = render(
    <AdjudicationSourcePane
      caseTitle="Case"
      sourceRender={{
        source_snapshot_id: "other-field",
        content: source.content,
        render_mode: "safe_text",
        anchors: [],
        truncated: false,
        omitted_anchor_count: 0,
      }}
      activeItem={item}
      documentHtml={null}
      htmlLoading={false}
      artifactAnchorUnavailable={false}
      view="text"
      onViewChange={vi.fn()}
      adjudicatorSpans={[]}
      adjudicatorLabel="Judge"
      pickingProvenance={false}
      onProvenancePick={vi.fn()}
    />,
  );
  const highlight = container.querySelector(".source-highlight-reviewer-overlap");
  expect(highlight).toHaveTextContent("first");
  expect(highlight).toHaveAttribute(
    "data-highlight-owners",
    "Highlighted by: Reviewer A · Proposal 1, Reviewer B · Proposal 1",
  );
});
