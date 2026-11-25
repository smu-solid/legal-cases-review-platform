import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { syntheticBundle } from "../../test/fixtures/reviewer";
import { AddedItemPanel } from "./AddedItemPanel";
import { GroupList } from "./GroupList";
import { emptyAnswer } from "./reviewerAnswerState";
import { newProposal, proposalItem } from "./reviewerProposals";
import { useReviewerKeyboard } from "./useReviewerKeyboard";

const group = {
  ...syntheticBundle.field_groups.find((g) => g.group_id === "cited_cases")!,
  add_item_label: "cited case",
};
const proposal = newProposal(group);
const item = proposalItem(proposal, "assignment");
afterEach(cleanup);

describe("reviewer additions", () => {
  it("places Add after existing rows, preserves their visibility, and keeps it outside counts", () => {
    const onAdd = vi.fn();
    render(
      <GroupList
        groups={[group]}
        answers={{}}
        activeItemId={group.items[0].review_unit_id}
        onSelect={vi.fn()}
        onAdd={onAdd}
        activeAddGroupId={group.group_id}
      />,
    );
    const add = screen.getByRole("button", { name: "+ Add cited case" });
    expect(add.parentElement?.lastElementChild).toBe(add);
    expect(add.parentElement?.querySelectorAll(".field-item")).toHaveLength(group.items.length + 1);
    expect(screen.getByText(`${group.completed_count}/${group.item_count}`)).toBeVisible();
    fireEvent.click(add);
    expect(onAdd).toHaveBeenCalledWith(group);
  });

  it("renders no correctness questions, focuses value, and explains compulsory provenance on disabled submit", () => {
    const onSubmit = vi.fn();
    render(
      <AddedItemPanel
        item={item}
        answer={emptyAnswer}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onSubmit={onSubmit}
        onRemove={vi.fn()}
        picking={false}
        onTogglePicking={vi.fn()}
        busy={false}
        error={null}
        readOnly={false}
      />,
    );
    expect(screen.getByLabelText("Proposed value")).toHaveFocus();
    expect(screen.queryByRole("heading", { name: /Reviewer-added/ })).toBeNull();
    expect(screen.queryByText(/Unsaved draft/)).toBeNull();
    expect(screen.queryByText(/Is the extracted value/)).toBeNull();
    const submit = screen.getByRole("button", { name: "Submit field" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(/compulsory/);
    expect(submit.parentElement).toHaveAttribute("tabindex", "0");
    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("handles an empty eligible group without inventing a field", () => {
    render(
      <GroupList
        groups={[{ ...group, items: [], item_count: 0, completed_count: 0 }]}
        answers={{}}
        activeItemId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "+ Add cited case" })).toBeVisible();
    expect(screen.getByText("0/0")).toBeVisible();
  });

  it("places the duplicate link above submit and leaves draft saving available", () => {
    const onOpen = vi.fn();
    const onSave = vi.fn();
    const feedback = {
      enabled: true,
      check: vi.fn(),
      error: undefined,
      data: {
        fingerprint: "a",
        conflicts: [
          {
            item_id: "existing",
            value: "Existing citation",
            kind: "confirmed" as const,
            reason: "Normalized substring",
            submitted: false,
          },
        ],
      },
    };
    const props = {
      item,
      answer: {
        ...emptyAnswer,
        corrected_value: "New citation",
        corrected_provenance_spans: [
          { evidence_window_id: "window", char_start: 0, char_end: 10, selected_text: "Citation" },
        ],
      },
      onChange: vi.fn(),
      onSave,
      onSubmit: vi.fn(),
      onRemove: vi.fn(),
      picking: false,
      onTogglePicking: vi.fn(),
      busy: false,
      error: null,
      readOnly: false,
      onOpenExisting: onOpen,
    };
    const { rerender } = render(<AddedItemPanel {...props} duplicateFeedback={feedback} />);
    const submit = screen.getByRole("button", { name: "Submit field" });
    const link = screen.getByRole("button", { name: /Click here to view the existing citation/ });
    expect(submit).toBeDisabled();
    expect(screen.getByText("Your marked provenance").compareDocumentPosition(link)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(link.compareDocumentPosition(submit)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledWith("existing");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(onSave).toHaveBeenCalledOnce();
    rerender(
      <AddedItemPanel
        {...props}
        duplicateFeedback={{ ...feedback, data: { fingerprint: "b", conflicts: [] } }}
      />,
    );
    expect(submit).toBeEnabled();
  });
});

it("isolates keyboard activation, composition, typing, repeats, and correctness shortcuts", () => {
  const actions = {
    step: vi.fn(),
    nextGroup: vi.fn(),
    value: vi.fn(),
    provenance: vi.fn(),
    save: vi.fn(),
    submit: vi.fn(),
    mark: vi.fn(),
    help: vi.fn(),
    escape: vi.fn(),
    ready: true,
    editable: true,
    added: true,
    modalOpen: false,
  };
  function Harness() {
    useReviewerKeyboard(actions);
    return (
      <>
        <input aria-label="Value" />
        <textarea aria-label="Note" />
        <button>Other action</button>
      </>
    );
  }
  render(<Harness />);
  const note = screen.getByLabelText("Note");
  fireEvent.keyDown(note, { key: "Enter" });
  fireEvent.keyDown(document.body, { key: "Enter", isComposing: true });
  fireEvent.keyDown(document.body, { key: "Enter", repeat: true });
  fireEvent.keyDown(screen.getByRole("button"), { key: "Enter" });
  expect(actions.submit).not.toHaveBeenCalled();
  const repeatEnter = new KeyboardEvent("keydown", {
    key: "Enter",
    repeat: true,
    cancelable: true,
    bubbles: true,
  });
  screen.getByRole("button").dispatchEvent(repeatEnter);
  expect(repeatEnter.defaultPrevented).toBe(true);
  fireEvent.keyDown(document.body, { key: "1" });
  fireEvent.keyDown(document.body, { key: "4" });
  expect(actions.value).not.toHaveBeenCalled();
  expect(actions.provenance).not.toHaveBeenCalled();
  fireEvent.keyDown(note, { key: "s", ctrlKey: true });
  expect(actions.save).toHaveBeenCalledOnce();
  fireEvent.keyDown(document.body, { key: "Enter" });
  expect(actions.submit).toHaveBeenCalledOnce();
  fireEvent.keyDown(document.body, { key: "m" });
  expect(actions.mark).toHaveBeenCalledOnce();
  const selectAll = new KeyboardEvent("keydown", {
    key: "a",
    ctrlKey: true,
    cancelable: true,
    bubbles: true,
  });
  note.dispatchEvent(selectAll);
  expect(selectAll.defaultPrevented).toBe(false);
});
