import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdjudicationWorkspaceItem } from "../../api/types";
import { AdjudicationDecisionPane } from "./AdjudicationDecisionPane";

const activeItem = {
  item_id: "field-1",
  item_label: "Case title",
  item_kind: "field",
  extracted_value_display: "National Aerated Water Co Pte Ltd",
  participation_status: "pending",
  evidence_window_ids: ["evidence-1"],
  submissions: [],
} as unknown as AdjudicationWorkspaceItem;

function renderPane(overrides: Partial<Parameters<typeof AdjudicationDecisionPane>[0]> = {}) {
  const props: Parameters<typeof AdjudicationDecisionPane>[0] = {
    activeItem,
    sourceContent: "selected source text",
    editable: true,
    verdict: "all_wrong",
    correctedValue: "",
    comment: "All answers are wrong",
    correctedProvenanceSpans: [
      {
        evidence_window_id: "evidence-1",
        char_start: 0,
        char_end: 8,
        selected_text: "selected",
      },
    ],
    pickingProvenance: false,
    commentRequired: true,
    canSave: true,
    canSubmit: true,
    saving: false,
    saveError: false,
    saveSuccess: false,
    submitting: false,
    submitError: false,
    onVerdictChange: vi.fn(),
    onCorrectedValueChange: vi.fn(),
    onCommentChange: vi.fn(),
    onToggleProvenancePicking: vi.fn(),
    onClearProvenance: vi.fn(),
    onSave: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<AdjudicationDecisionPane {...props} />);
  return props;
}

describe("AdjudicationDecisionPane", () => {
  it("shows the selected field's extracted value above reviewer answers and the final decision", () => {
    renderPane({
      activeItem: {
        ...activeItem,
        submissions: [
          {
            submission_id: "submission-1",
            pseudonym: "Reviewer Owl",
            reviewer: { display_name: "Aisha Rahman", email: "aisha@example.test" },
            value_correct: true,
            provenance_correct: true,
            corrected_provenance_spans: [],
            evidence_ids: [],
            corrected_value: null,
            corrected_value_display: null,
            failure_reason: null,
            comment: null,
            submitted_at: "2026-08-18T10:00:00Z",
          },
        ],
      },
    });
    const extractedValue = screen.getByText("National Aerated Water Co Pte Ltd");
    const reviewerAnswer = screen.getAllByText("Aisha Rahman")[0];
    const finalDecision = screen.getByText("Final decision");
    expect(
      extractedValue.compareDocumentPosition(reviewerAnswer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      extractedValue.compareDocumentPosition(finalDecision) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("uses the shared missing-value presentation", () => {
    renderPane({
      activeItem: {
        ...activeItem,
        extracted_value_display: "No value extracted",
      },
    });
    expect(screen.getByText("No value extracted")).toHaveClass("extracted-value-missing");
  });

  it("allows an editable untouched field to choose its first final decision", () => {
    const props = renderPane({ verdict: null });
    fireEvent.click(screen.getByRole("radio", { name: "All equivalent / supported" }));
    expect(props.onVerdictChange).toHaveBeenCalledWith("all_equivalent_supported");
  });

  it("accepts a note before selecting a verdict while final submission stays disabled", () => {
    const props = renderPane({ verdict: null, comment: "", canSubmit: false });
    const note = screen.getByLabelText(/adjudicator note/i);
    expect(note).toBeEnabled();
    fireEvent.change(note, { target: { value: "Initial private note" } });
    expect(props.onCommentChange).toHaveBeenCalledExactlyOnceWith("Initial private note");
    expect(screen.getByRole("button", { name: "Submit adjudication" })).toBeDisabled();
  });

  it("keeps the note read-only in a non-editable workspace without a verdict", () => {
    renderPane({ editable: false, verdict: null, comment: "Saved private note" });
    expect(screen.getByLabelText(/adjudicator note/i)).toBeDisabled();
    expect(screen.getByLabelText(/adjudicator note/i)).toHaveValue("Saved private note");
  });

  it("offers optional provenance marking only for editable all-wrong decisions", () => {
    const props = renderPane();
    fireEvent.click(screen.getByRole("button", { name: "Mark corrected provenance in source" }));
    expect(props.onToggleProvenancePicking).toHaveBeenCalledOnce();
    expect(screen.getByText("“selected”")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(props.onClearProvenance).toHaveBeenCalledWith(0);
  });

  it("keeps submitted provenance visible but read-only", () => {
    renderPane({ editable: false });
    expect(screen.queryByRole("button", { name: /mark corrected provenance/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "clear" })).toBeNull();
    expect(screen.getByText("“selected”")).toBeInTheDocument();
  });
});

it("puts proposal preferences and other outcomes in one Final decision radio group", () => {
  renderPane({
    activeItem: {
      ...activeItem,
      proposal_source: { snapshotId: "snapshot", version: "v" },
      proposal_item: {
        id: "item",
        proposals: [
          {
            id: "p",
            value: "Citation",
            note: "",
            provenance: [],
            reviewer_key: "a",
            reviewer_label: "Alice",
            proposal_number: 1,
          },
        ],
        origin: "automatic",
        matching_reasons: [],
        different_values: false,
        extracted_adjudication_id: null,
      },
    } as unknown as AdjudicationWorkspaceItem,
  });
  const preferred = screen.getByRole("radio", { name: "Alice · Proposal 1 preferred Citation" });
  const equivalent = screen.getByRole("radio", { name: "All equivalent / supported" });
  const final = screen.getByRole("group", { name: "Final decision" });
  expect(final).toContainElement(preferred);
  expect(final).toContainElement(equivalent);
  expect(preferred).toHaveAttribute("name", equivalent.getAttribute("name"));
  expect(screen.queryByRole("group", { name: "Preferred proposal" })).toBeNull();
});
