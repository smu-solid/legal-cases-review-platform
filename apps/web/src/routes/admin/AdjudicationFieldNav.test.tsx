import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdjudicationCaseWorkspace } from "../../api/types";
import { AdjudicationFieldNav } from "./AdjudicationFieldNav";

const item = (id: string, status: "pending" | "submitted") =>
  ({
    item_id: id,
    review_unit_id: id,
    item_label: "Cited case",
    extracted_value_display: `Citation ${id}`,
    participation_status: status,
    draft: null,
  }) as AdjudicationCaseWorkspace["field_groups"][number]["items"][number];

describe("AdjudicationFieldNav", () => {
  it("keeps the agreement controls outside the scrolling group region and shows completion", () => {
    const groups = [
      {
        group_id: "citations",
        group_label: "Cited cases",
        group_kind: "non_atomic" as const,
        description: null,
        order: 1,
        items: [{ ...item("one", "submitted") }, item("two", "pending")],
      },
    ];
    const { container } = render(
      <AdjudicationFieldNav
        groups={groups}
        activeItem={groups[0].items[0]}
        filter="all"
        onFilterChange={vi.fn()}
        onSelect={vi.fn()}
      />,
    );

    const nav = screen.getByRole("navigation", { name: /adjudication fields/i });
    expect(nav.firstElementChild).toHaveClass("adjudication-field-filter");
    expect(nav.lastElementChild).toHaveClass("adjudication-field-groups");
    expect(screen.getByRole("button", { name: /cited cases 1\/2/i })).toBeInTheDocument();
    expect(container.querySelectorAll(".field-item")).toHaveLength(2);
  });

  it("uses the same repeatable-group collapse behavior as the reviewer workspace", () => {
    const onSelect = vi.fn();
    const groups = [
      {
        group_id: "citations",
        group_label: "Cited cases",
        group_kind: "non_atomic" as const,
        description: null,
        order: 1,
        items: [item("one", "submitted"), item("two", "pending")],
      },
    ];
    render(
      <AdjudicationFieldNav
        groups={groups}
        activeItem={groups[0].items[0]}
        filter="all"
        onFilterChange={vi.fn()}
        onSelect={onSelect}
      />,
    );
    const heading = screen.getByRole("button", { name: /cited cases 1\/2/i });

    fireEvent.click(heading);
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /citation one/i })).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(heading);
    expect(heading).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /citation one/i })).toBeInTheDocument();
    expect(onSelect).toHaveBeenCalledWith("one");
  });
});
