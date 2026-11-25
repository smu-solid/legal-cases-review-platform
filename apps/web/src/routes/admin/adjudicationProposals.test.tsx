import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProposalWorkspace } from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import { AdjudicationDraftRecovery } from "./AdjudicationDraftRecovery";
import {
  hydrateProposalDecision,
  mergeProposalWorkspace,
  proposalDecisionBody,
  proposalDecisionReady,
} from "./adjudicationProposals";
import { useAdjudicationKeyboard } from "./useAdjudicationKeyboard";

const field = {
  item_id: "field",
  review_unit_id: "unit",
  adjudication_id: "adj",
  membership_version: 0,
  item_label: "Citation",
  extracted_value_display: "Original",
  participation_status: "submitted",
  submissions: [],
  evidence_window_ids: [],
} as unknown as AdjudicationWorkspaceItem;
const base = {
  mode: "read_only",
  field_groups: [
    { group_id: "cited_cases", items: [field] },
    { group_id: "statutes_cited", items: [] },
  ],
} as unknown as AdjudicationCaseWorkspace;
const extra = {
  ready: true,
  required_reviews: 3,
  source_snapshot_id: "snapshot",
  source_version: "a".repeat(64),
  items: [
    {
      id: "added",
      group_id: "cited_cases",
      extracted_adjudication_id: null,
      reviewer_count: 1,
      state: "pending",
      lock_version: 1,
      proposals: [
        {
          id: "proposal",
          value: "My citation",
          reviewer_key: "r",
          reviewer_label: "R",
          proposal_number: 1,
        },
      ],
      origin: "automatic",
      matching_reasons: [],
      different_values: false,
    },
  ],
} as unknown as ProposalWorkspace;
function authored() {
  return mergeProposalWorkspace(base, extra)!.field_groups[0].items[1];
}

describe("proposal workspace integration", () => {
  it("keeps originals visible, uses N, and permits one author's eligible proposal", () => {
    const merged = mergeProposalWorkspace(base, extra)!;
    expect(merged.field_groups[0].items).toHaveLength(2);
    expect(merged.field_groups[0].items[0]).toBe(field);
    expect(merged.mode).toBe("edit");
    const item = authored();
    expect(item.required_reviews).toBe(3);
    expect(item.submitted_reviews).toBe(1);
    expect(
      proposalDecisionReady(item, {
        ...hydrateProposalDecision(item, ""),
        verdict: "proposal:proposal",
      }),
    ).toBe(true);
  });
  it("replaces a combined extracted item once, retaining its identity and source", () => {
    const merged = mergeProposalWorkspace(base, {
      ...extra,
      items: [{ ...extra.items[0], extracted_adjudication_id: "adj" }],
    })!;
    expect(merged.field_groups[0].items).toHaveLength(1);
    expect(merged.field_groups[0].items[0]).toMatchObject({
      item_id: "field",
      extracted_value_display: "Original",
      document_unit_id: "unit",
    });
  });
  it("does not expose proposals before the case gate and supports multiple/empty groups", () => {
    expect(mergeProposalWorkspace(base, { ...extra, ready: false })).toBe(base);
    const merged = mergeProposalWorkspace(base, {
      ...extra,
      items: [...extra.items, { ...extra.items[0], id: "statute", group_id: "statutes_cited" }],
    })!;
    expect(merged.field_groups[1].items[0].proposal_item?.id).toBe("statute");
  });
  it("persists exact preference and retains the input's original source version", () => {
    const item = authored();
    const local = {
      ...hydrateProposalDecision(item, "source"),
      verdict: "proposal:proposal" as const,
      proposalSource: { snapshotId: "old", version: "old-version" },
      correctedProvenanceSpans: [
        { evidence_window_id: "ignored", char_start: 1, char_end: 4, selected_text: "our" },
      ],
    };
    expect(proposalDecisionBody(item, local)).toMatchObject({
      preferred_proposal_id: "proposal",
      provenance: [
        { source_snapshot_id: "old", source_version: "old-version", char_start: 1, char_end: 4 },
      ],
    });
  });
  it("requires notes and marking for corrections, but permits a reasoned rejection", () => {
    const item = authored(),
      local = hydrateProposalDecision(item, "");
    expect(
      proposalDecisionReady(item, {
        ...local,
        verdict: "all_wrong",
        correctedValue: "New",
        comment: "Why",
      }),
    ).toBe(false);
    expect(
      proposalDecisionReady(item, { ...local, verdict: "all_wrong", comment: "Not a cited case" }),
    ).toBe(true);
    expect(proposalDecisionReady(item, { ...local, verdict: "proposal:absent" })).toBe(false);
  });
  it("preserves a draft when its item is replaced and requires explicit reassessment", () => {
    const item = authored(),
      draft = { ...hydrateProposalDecision(item, ""), dirty: true, comment: "Keep this note" };
    const refresh = vi.fn(),
      restore = vi.fn(),
      reassess = vi.fn();
    render(
      <AdjudicationDraftRecovery
        items={[item]}
        active={item}
        drafts={{ old: draft, added: { ...draft, proposalVersion: 0 } }}
        onRefresh={refresh}
        onRestore={restore}
        onReassess={reassess}
      />,
    );
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("Keep this note");
    fireEvent.click(screen.getByRole("button", { name: /Refresh workspace/ }));
    expect(refresh).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: /reassessed/ }));
    expect(reassess).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: /Use this draft/ }));
    expect(restore).toHaveBeenCalledWith("old");
  });
});

describe("adjudication keyboard isolation", () => {
  function setup() {
    const item = authored();
    const props = {
      activeItem: item,
      activeDecision: hydrateProposalDecision(item, ""),
      editable: true,
      visibleItems: [field, item],
      bundle: base,
      onUpdate: vi.fn(),
      onSelect: vi.fn(),
      onSave: vi.fn(),
      onSubmit: vi.fn(),
      onTogglePicking: vi.fn(),
      onToggleShortcuts: vi.fn(),
      onDismiss: vi.fn(),
    };
    const { rerender } = renderHook((value) => useAdjudicationKeyboard(value), {
      initialProps: props,
    });
    return { ...props, rerender };
  }
  it("ignores typing/composition/repeat and leaves focused-button Enter to its button", () => {
    const props = setup();
    render(
      <>
        <textarea aria-label="Note" />
        <button>Save</button>
      </>,
    );
    for (const target of [screen.getByRole("textbox"), screen.getByRole("button")])
      fireEvent.keyDown(target, { key: "Enter" });
    fireEvent.keyDown(document, { key: "Enter", isComposing: true });
    fireEvent.keyDown(document, { key: "Enter", repeat: true });
    expect(props.onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Enter" });
    expect(props.onSubmit).toHaveBeenCalledOnce();
  });
  it("saves while typing, leaves Select All, and marks proposals only for All wrong", () => {
    const props = setup();
    render(<textarea aria-label="Note" />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "s", ctrlKey: true });
    expect(props.onSave).toHaveBeenCalledOnce();
    expect(fireEvent.keyDown(screen.getByRole("textbox"), { key: "a", metaKey: true })).toBe(true);
    fireEvent.keyDown(document, { key: "m" });
    expect(props.onTogglePicking).not.toHaveBeenCalled();
    props.rerender({
      ...props,
      activeDecision: { ...props.activeDecision, verdict: "all_wrong" },
    });
    fireEvent.keyDown(document, { key: "m" });
    expect(props.onTogglePicking).toHaveBeenCalledOnce();
    props.rerender({
      ...props,
      activeDecision: { ...props.activeDecision, verdict: "all_equivalent_supported" },
    });
    fireEvent.keyDown(document, { key: "m" });
    expect(props.onTogglePicking).toHaveBeenCalledOnce();
    fireEvent.keyDown(document, { key: "k" });
    expect(props.onSelect).toHaveBeenCalledWith("field");
    fireEvent.keyDown(document, { key: "?" });
    expect(props.onToggleShortcuts).toHaveBeenCalledOnce();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onDismiss).toHaveBeenCalledOnce();
  });
});

it("preserves server-verified source snapshot identities in the live workspace", () => {
  const merged = mergeProposalWorkspace(base, {
    ...extra,
    source_snapshot_ids: ["snapshot", "other-field"],
  })!;
  expect(merged.field_groups[0].items[1].proposal_source?.snapshotIds).toEqual([
    "snapshot",
    "other-field",
  ]);
});
