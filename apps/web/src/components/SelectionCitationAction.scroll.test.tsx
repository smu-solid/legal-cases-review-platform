import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SelectionCitationAction } from "./SelectionCitationAction";

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  cleanup();
});

function selectCitation() {
  const root = createRef<HTMLPreElement>();
  const onAdd = vi.fn();
  render(
    <>
      <pre ref={root} tabIndex={0}>
        Before [2001] SGHC 2 after
      </pre>
      <SelectionCitationAction root={root} enabled onAdd={onAdd} resetKey="case-1" />
    </>,
  );
  const element = root.current!;
  element.scrollTop = 100;
  const scroll = vi.spyOn(element, "scrollTo");
  const range = document.createRange();
  range.setStart(element.firstChild!, 7);
  range.setEnd(element.firstChild!, 20);
  Object.defineProperty(range, "getBoundingClientRect", {
    value: () => new DOMRect(20, 100, 120, 20),
  });
  vi.spyOn(range, "cloneRange").mockReturnValue(range);
  window.getSelection()!.addRange(range);
  fireEvent.mouseUp(element);
  expect(screen.getByRole("button", { name: /^Add cited case$/ })).toBeVisible();
  return { element, scroll, onAdd };
}

describe("citation selection during source scrolling", () => {
  it("stops an earlier animated scroll without moving the selection", () => {
    const { element, scroll } = selectCitation();
    expect(scroll).toHaveBeenCalledWith({ top: 100, left: 0, behavior: "instant" });
    expect(element).toHaveFocus();
    expect(element.scrollTop).toBe(100);
    expect(window.getSelection()?.toString()).toBe("[2001] SGHC 2");
  });

  it("retains the action on a queued scroll event with no further movement", () => {
    const { element, onAdd } = selectCitation();
    fireEvent.scroll(element);
    fireEvent.click(screen.getByRole("button", { name: /^Add cited case$/ }));
    expect(onAdd).toHaveBeenCalledExactlyOnceWith(7, 20);
    expect(window.getSelection()?.toString()).toBe("");
  });

  it("still dismisses the action when the reviewer scrolls the source", () => {
    const { element } = selectCitation();
    element.scrollTop = 120;
    fireEvent.scroll(element);
    expect(screen.queryByRole("button", { name: /^Add cited case$/ })).not.toBeInTheDocument();
  });

  it("still dismisses the action when the viewport is resized", () => {
    selectCitation();
    fireEvent.resize(window);
    expect(screen.queryByRole("button", { name: /^Add cited case$/ })).not.toBeInTheDocument();
  });

  it("retains the action for an unchanged ancestor but dismisses it when the source moves", () => {
    const { element } = selectCitation();
    fireEvent.scroll(window);
    expect(screen.getByRole("button", { name: /^Add cited case$/ })).toBeVisible();
    vi.spyOn(element, "getBoundingClientRect").mockReturnValue(new DOMRect(0, -20, 300, 200));
    fireEvent.scroll(window);
    expect(screen.queryByRole("button", { name: /^Add cited case$/ })).not.toBeInTheDocument();
  });

  it("dismisses the action after horizontal source scrolling", () => {
    const { element } = selectCitation();
    element.scrollLeft = 20;
    fireEvent.scroll(element);
    expect(screen.queryByRole("button", { name: /^Add cited case$/ })).not.toBeInTheDocument();
  });
});
