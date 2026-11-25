import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { InfoTooltip } from "./InfoTooltip";

describe("InfoTooltip", () => {
  afterEach(() => {
    cleanup();
  });

  function renderTooltip() {
    render(<InfoTooltip label="What is this?" text="Explanation text" />);
    return screen.getByRole("button", { name: "What is this?" });
  }

  it("opens on click and sets aria-expanded + aria-describedby pointing at the tooltip element", () => {
    const button = renderTooltip();

    fireEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
    const describedBy = button.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveAttribute("id", describedBy);
    expect(tooltip.textContent).toBe("Explanation text");
  });

  it("closes on Escape", () => {
    const button = renderTooltip();

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("closes on blur", () => {
    const button = renderTooltip();

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.blur(button);

    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on focus, closes when unfocused (non-pinned)", () => {
    const button = renderTooltip();

    fireEvent.focus(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.blur(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("opens on mouseEnter and closes on mouseLeave when not pinned", () => {
    const button = renderTooltip();

    fireEvent.mouseEnter(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.mouseLeave(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the popover pinned open on mouseLeave after a click, until clicked again or blurred", () => {
    const button = renderTooltip();

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.mouseLeave(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  function mockRects(buttonRect: Partial<DOMRect>, popoverRect: Partial<DOMRect>) {
    const original = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function mocked(this: Element) {
      const rect = this.matches(".info-tooltip-button") ? buttonRect : popoverRect;
      return {
        top: 0,
        bottom: 0,
        left: 0,
        right: 0,
        width: 0,
        height: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
        ...rect,
      } as DOMRect;
    };
    return () => {
      Element.prototype.getBoundingClientRect = original;
    };
  }

  it("clamps the popover horizontally so it stays fully inside the viewport near the right edge", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1000 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });

    const restore = mockRects(
      {
        top: 400,
        bottom: 420,
        left: window.innerWidth - 10,
        right: window.innerWidth,
        width: 20,
        height: 20,
      },
      { top: 0, bottom: 40, left: 0, right: 240, width: 240, height: 40 },
    );

    const button = renderTooltip();
    fireEvent.click(button);

    const tooltip = screen.getByRole("tooltip");
    const left = Number.parseFloat(tooltip.style.left);
    expect(left).toBeGreaterThanOrEqual(8);
    expect(left + 240).toBeLessThanOrEqual(window.innerWidth - 8);

    restore();
  });

  it("flips below the icon when there is not enough room above", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1000 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });

    const restore = mockRects(
      { top: 5, bottom: 25, left: 100, right: 120, width: 20, height: 20 },
      { top: 0, bottom: 40, left: 0, right: 240, width: 240, height: 40 },
    );

    const button = renderTooltip();
    fireEvent.click(button);

    const tooltip = screen.getByRole("tooltip");
    const top = Number.parseFloat(tooltip.style.top);
    expect(top).toBeGreaterThan(25);

    restore();
  });
});
