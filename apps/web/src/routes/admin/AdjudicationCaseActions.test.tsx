import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdjudicationWorkspaceItem } from "../../api/types";
import {
  AdjudicationShortcutsModal,
  AdjudicationSubmitPreviewModal,
} from "./AdjudicationCaseActions";
import { hydrateAdjudicationDecision, verdictOptions } from "./adjudicationDecisionState";

function item(): AdjudicationWorkspaceItem {
  return {
    item_id: "field-1",
    review_unit_id: "unit-1",
    adjudication_id: "adj-1",
    item_label: "Case title",
    item_kind: "field",
    extracted_value_display: "Example",
    review_kind: "field",
    required_reviews: 2,
    submitted_reviews: 2,
    evidence_window_ids: ["evidence-1"],
    submissions: [
      {
        submission_id: "one",
        pseudonym: "Reviewer 1",
        reviewer: { display_name: "Alice", email: "alice@example.test" },
      },
      {
        submission_id: "two",
        pseudonym: "Reviewer 2",
        reviewer: { display_name: "Bob", email: "bob@example.test" },
      },
    ],
    assessment_targets: [],
    evidence_windows: [],
    participation_status: "pending",
  } as unknown as AdjudicationWorkspaceItem;
}

describe("adjudication case actions", () => {
  it("shows one numbered shortcut for every two-reviewer verdict", () => {
    render(<AdjudicationShortcutsModal options={verdictOptions(item())} onClose={vi.fn()} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("Mark corrected provenance (All wrong only)")).toBeInTheDocument();
  });

  it("previews adjudication-specific columns and confirms complete rows", () => {
    const onConfirm = vi.fn();
    const decision = {
      ...hydrateAdjudicationDecision(item(), "source"),
      verdict: "all_equivalent_supported" as const,
    };
    render(
      <AdjudicationSubmitPreviewModal
        caseTitle="Example case"
        campaignName="Pilot"
        rows={[{ item: item(), decision, ready: true }]}
        busy={null}
        error={null}
        onCancel={vi.fn()}
        onSaveAll={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByText("Final decision")).toBeInTheDocument();
    expect(screen.getByText("Final / corrected value")).toBeInTheDocument();
    expect(screen.getByText("Note")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm & submit case" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
