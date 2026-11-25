import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { syntheticBundle } from "../../test/fixtures/reviewer";
import { GroupList } from "./GroupList";
import { mergeHydratedAnswers } from "./reviewerAnswerState";

// Covers the compact left-nav card format: dot-first rows, no visible per-card status text (the
// dot color plus the button's aria-label/title carry it), and no repeated item label on repeatable
// members.
describe("GroupList compact field cards", () => {
  afterEach(() => {
    cleanup();
  });

  const noop = () => {};

  function renderList(activeItemId: string | null = null) {
    return render(
      <GroupList
        groups={syntheticBundle.field_groups}
        activeItemId={activeItemId}
        answers={{}}
        onSelect={noop}
      />,
    );
  }

  it("keeps unsaved local answers when the same assignment bundle is hydrated again", () => {
    const item = syntheticBundle.field_groups[0].items[0];
    const unsaved = {
      value_correct: false,
      provenance_correct: false,
      corrected_value: "Local unsaved correction",
      comment: "Keep this draft",
      failure_reason: "value_incorrect",
      evidence_ids: item.evidence_window_ids,
      corrected_provenance_spans: [],
      saved: false,
      submitted: false,
    };

    const merged = mergeHydratedAnswers(syntheticBundle, { [item.review_unit_id]: unsaved });

    expect(merged[item.review_unit_id]).toEqual(unsaved);
    expect(Object.keys(merged)).toHaveLength(
      syntheticBundle.field_groups.flatMap((group) => group.items).length,
    );
  });

  it("shows an atomic field's label and value without visible status text", () => {
    renderList();

    const card = screen.getByRole("button", {
      name: /Neutral citation: \[2017\] SGHC 12 \(Not started\)/,
    });
    // Label and value are visible; the status wording is not part of the rendered text.
    expect(card.textContent).toContain("Neutral citation");
    expect(card.textContent).toContain("[2017] SGHC 12");
    expect(card.textContent).not.toContain("Not started");
    // The status dot itself remains, colour-coded by status kind.
    expect(card.querySelector(".status-dot-not_started")).not.toBeNull();
  });

  it("shows only dot + extracted value on repeatable members (no repeated item label)", () => {
    renderList();

    // Expand the repeatable "Cited cases" group first (collapsed by default with no active member).
    fireEvent.click(screen.getByRole("button", { name: /Cited cases/ }));

    const member = screen.getByRole("button", {
      name: /Lee v Public Prosecutor \[2015\] SGCA 3 \(Not started\)/,
    });
    // Exactly one visible text node: the extracted value. The item label only appears within it
    // because these synthetic citations embed the case name; the status text must not render.
    expect(member.textContent).toBe("Lee v Public Prosecutor [2015] SGCA 3");
    expect(member.querySelector(".field-item-value")).not.toBeNull();
    expect(member.querySelector(".field-item-label")).toBeNull();
  });

  it("does not render a status-dot legend (status is carried by per-item dots and aria-labels)", () => {
    const { container } = renderList();

    expect(container.querySelector(".status-legend")).toBeNull();
  });

  it("keeps a repeatable group's members reachable while one is active (group stays open)", () => {
    const activeId = syntheticBundle.field_groups[1].items[0].review_unit_id;
    renderList(activeId);

    // Both members render without any toggle click because the active member pins the group open.
    expect(
      screen.getByRole("button", { name: /Lee v Public Prosecutor \[2015\] SGCA 3/ }),
    ).toHaveClass("is-active");
    expect(
      screen.getByRole("button", { name: /Ng v Comptroller \[2012\] SGHC 44/ }),
    ).not.toHaveClass("is-active");
  });

  it("moves keyboard focus with the active field instead of leaving a stale focus ring", () => {
    const first = syntheticBundle.field_groups[0].items[0];
    const second = syntheticBundle.field_groups[0].items[1];
    const { rerender } = render(
      <GroupList
        groups={syntheticBundle.field_groups}
        activeItemId={first.review_unit_id}
        answers={{}}
        onSelect={noop}
      />,
    );
    screen.getByRole("button", { name: new RegExp(first.item_label) }).focus();

    rerender(
      <GroupList
        groups={syntheticBundle.field_groups}
        activeItemId={second.review_unit_id}
        answers={{}}
        onSelect={noop}
      />,
    );

    expect(screen.getByRole("button", { name: new RegExp(second.item_label) })).toHaveFocus();
  });

  it("collapses an expanded repeatable group via the header even while a member is active, and re-expands on a second click", () => {
    const activeId = syntheticBundle.field_groups[1].items[0].review_unit_id;
    const onSelect = vi.fn();
    const { rerender } = render(
      <GroupList
        groups={syntheticBundle.field_groups}
        activeItemId={activeId}
        answers={{}}
        onSelect={onSelect}
      />,
    );

    // The active member pins the group open by default (no manual override yet).
    expect(
      screen.getByRole("button", { name: /Lee v Public Prosecutor \[2015\] SGCA 3/ }),
    ).toBeInTheDocument();

    const header = screen.getByRole("button", { name: /Cited cases/ });
    fireEvent.click(header);

    // Collapsing must not touch the selection -- otherwise activeInGroup would force it back open.
    expect(onSelect).not.toHaveBeenCalled();
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: /Lee v Public Prosecutor \[2015\] SGCA 3/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Ng v Comptroller \[2012\] SGHC 44/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(header);

    // Re-expanding selects the first member (existing behavior) and reveals the members again.
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(syntheticBundle.field_groups[1].items[0]);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: /Lee v Public Prosecutor \[2015\] SGCA 3/ }),
    ).toBeInTheDocument();

    // Rerendering with an active item from another group clears the manual override, so the
    // now-inactive repeatable group collapses again (documented default behavior).
    const otherId = syntheticBundle.field_groups[0].items[0].review_unit_id;
    rerender(
      <GroupList
        groups={syntheticBundle.field_groups}
        activeItemId={otherId}
        answers={{}}
        onSelect={onSelect}
      />,
    );

    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: /Lee v Public Prosecutor \[2015\] SGCA 3/ }),
    ).not.toBeInTheDocument();
  });
});
