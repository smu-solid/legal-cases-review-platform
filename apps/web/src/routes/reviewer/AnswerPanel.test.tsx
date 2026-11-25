import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GroupItem } from "../../api/types";
import { syntheticBundle } from "../../test/fixtures/reviewer";
import { AnswerPanel } from "./AnswerPanel";

// Covers the "missing extracted value" reviewer-workspace rule: a `missing` item must render an
// explicit "No value extracted" state and hard-lock the "Is the extracted value correct?" control
// to "No" (the backend rejects value_correct=true for these items with a 422), while a `present`
// item -- today's default and by far the common case -- must render exactly as before.
describe("AnswerPanel missing-value lock", () => {
  afterEach(() => {
    cleanup();
  });

  const baseItem = syntheticBundle.field_groups[0].items[0];

  const emptyAnswer = {
    value_correct: null as boolean | null,
    provenance_correct: null as boolean | null,
    corrected_value: "",
    comment: "",
    failure_reason: "",
    evidence_ids: baseItem.evidence_window_ids,
    corrected_provenance_spans: [],
    saved: false,
    submitted: false,
  };

  function renderPanel(item: GroupItem, answer = emptyAnswer, onChange = vi.fn()) {
    render(
      <AnswerPanel
        activeItem={item}
        answer={answer}
        onChange={onChange}
        onSave={() => {}}
        onSubmit={() => {}}
        isSaving={false}
        isSubmitting={false}
        saveError={null}
        submitError={null}
        onRefresh={() => {}}
        pickingProvenance={false}
        onTogglePicking={() => {}}
      />,
    );
    return onChange;
  }

  // The "Is the extracted value correct?" control is the first of two Yes/No toggle groups on the
  // panel (the second is "Is the highlighted provenance correct?"), so scope queries to its
  // fieldset rather than matching "Yes"/"No" text globally.
  function valueCorrectFieldset() {
    return screen.getByRole("group", { name: /Is the extracted value correct\?/ });
  }

  it("present item: renders the extracted value plainly and both Yes/No are selectable (unchanged behavior)", () => {
    renderPanel(baseItem);

    expect(screen.getByText(baseItem.extracted_value_display)).not.toHaveClass(
      "extracted-value-missing",
    );

    const yesButton = within(valueCorrectFieldset()).getByRole("button", { name: "Yes" });
    expect(yesButton).not.toBeDisabled();
  });

  it("missing item: shows a visually distinct 'No value extracted' state", () => {
    const missingItem: GroupItem = {
      ...baseItem,
      extraction_state: "missing",
      extracted_value_display: "No value extracted",
      extracted_value_raw: null,
      evidence_window_ids: [],
    };

    renderPanel(missingItem);

    const valueEl = screen.getByText("No value extracted");
    expect(valueEl).toHaveClass("extracted-value-missing");
  });

  it("missing item: 'Yes' is disabled and cannot be selected; 'No' is force-selected", () => {
    const missingItem: GroupItem = {
      ...baseItem,
      extraction_state: "missing",
      extracted_value_display: "No value extracted",
      extracted_value_raw: null,
      evidence_window_ids: [],
    };
    const lockedAnswer = { ...emptyAnswer, value_correct: false as const, evidence_ids: [] };
    const onChange = renderPanel(missingItem, lockedAnswer);

    const fieldset = valueCorrectFieldset();
    const yesButton = within(fieldset).getByRole("button", { name: "Yes" });
    const noButton = within(fieldset).getByRole("button", { name: "No" });

    expect(yesButton).toBeDisabled();
    expect(noButton).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(yesButton);

    // Disabled buttons don't fire onClick in the DOM, and the handler itself also guards against
    // ever propagating value_correct=true for a missing item -- assert both never happened.
    expect(onChange).not.toHaveBeenCalled();
  });

  it("missing item: the provenance 'Yes' is also disabled and force-selected to 'No'", () => {
    const missingItem: GroupItem = {
      ...baseItem,
      extraction_state: "missing",
      extracted_value_display: "No value extracted",
      extracted_value_raw: null,
      evidence_window_ids: [],
    };
    const lockedAnswer = {
      ...emptyAnswer,
      value_correct: false as const,
      provenance_correct: false as const,
      evidence_ids: [],
    };
    const onChange = renderPanel(missingItem, lockedAnswer);

    const provenanceFieldset = screen.getByRole("group", {
      name: /Is the highlighted provenance correct\?/,
    });
    const yesButton = within(provenanceFieldset).getByRole("button", { name: "Yes" });
    const noButton = within(provenanceFieldset).getByRole("button", { name: "No" });

    expect(yesButton).toBeDisabled();
    expect(noButton).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(yesButton);
    expect(onChange).not.toHaveBeenCalled();
  });
});
