import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { resolveProvenancePick } from "./provenancePick";

// Keep the native selection intact until the reviewer explicitly chooses to add it.
export function SelectionCitationAction({
  root,
  enabled,
  onAdd,
  resetKey,
}: {
  root: RefObject<HTMLPreElement | null>;
  enabled: boolean;
  onAdd?: (start: number, end: number) => void;
  resetKey: string;
}) {
  const [picked, setPicked] = useState<{
    charStart: number;
    charEnd: number;
    range: Range;
  } | null>(null);
  const [hovering, setHovering] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    const button = buttonRef.current;
    if (!picked || !hovering || !button) return;
    const rect = picked.range.getBoundingClientRect();
    button.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - button.offsetWidth - 8))}px`;
    button.style.top = `${rect.top - button.offsetHeight - 2}px`;
  }, [picked, hovering]);
  useEffect(() => {
    setPicked(null);
    if (!enabled) return;
    function viewportPosition() {
      const element = root.current;
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return [element.scrollTop, element.scrollLeft, rect.top, rect.left];
    }
    let selectionPosition: number[] | null = null;
    function select() {
      const selection = window.getSelection();
      const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
      if (!range || !root.current?.contains(range.commonAncestorContainer)) {
        setPicked(null);
        return;
      }
      const result = resolveProvenancePick(root.current, range);
      if (!result) {
        setPicked(null);
        return;
      }
      // A selection takes control from the earlier active-anchor animation. Freeze at the
      // current reading position so its remaining frames cannot dismiss this new action.
      const selectedRange = range.cloneRange();
      root.current.focus({ preventScroll: true });
      selection!.removeAllRanges();
      selection!.addRange(selectedRange);
      root.current.scrollTo({
        top: root.current.scrollTop,
        left: root.current.scrollLeft,
        behavior: "instant",
      });
      selectionPosition = viewportPosition();
      setPicked({
        ...result,
        range: selectedRange,
      });
      setHovering(true);
    }
    function clear() {
      selectionPosition = null;
      setPicked(null);
    }
    function scrolled() {
      const previous = selectionPosition;
      const current = viewportPosition();
      // Browsers can deliver a scroll event queued before mouseup. Only dismiss if the
      // source actually moved after selection, including movement of its ancestors.
      if (!previous || !current || current.some((value, index) => value !== previous[index])) {
        clear();
      }
    }
    const element = root.current;
    element?.addEventListener("mouseup", select);
    const keyup = (event: KeyboardEvent) => {
      if (event.key !== "Escape") select();
    };
    element?.addEventListener("keyup", keyup);
    element?.addEventListener("scroll", scrolled);
    const selectionChanged = () => {
      if (!window.getSelection()?.toString()) clear();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") clear();
    };
    const dismiss = (event: MouseEvent) => {
      if (!(event.target as Element)?.closest?.(".selection-add-citation")) clear();
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", escape);
    document.addEventListener("selectionchange", selectionChanged);
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", clear);
    return () => {
      element?.removeEventListener("mouseup", select);
      element?.removeEventListener("keyup", keyup);
      element?.removeEventListener("scroll", scrolled);
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", escape);
      document.removeEventListener("selectionchange", selectionChanged);
      window.removeEventListener("scroll", scrolled, true);
      window.removeEventListener("resize", clear);
    };
  }, [enabled, root, resetKey]);
  useEffect(() => {
    if (!picked) return;
    function move(event: MouseEvent) {
      const button = (event.target as Element)?.closest?.(".selection-add-citation");
      const overRange = [...picked!.range.getClientRects()].some(
        (rect) =>
          event.clientX >= rect.left &&
          event.clientX <= rect.right &&
          event.clientY >= rect.top - 40 &&
          event.clientY <= rect.bottom,
      );
      setHovering(Boolean(button) || overRange);
    }
    document.addEventListener("mousemove", move);
    return () => document.removeEventListener("mousemove", move);
  }, [picked]);
  if (!enabled || !picked || !hovering) return null;
  return createPortal(
    <button
      ref={buttonRef}
      type="button"
      className="selection-add-citation primary-button"
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => {
        onAdd?.(picked.charStart, picked.charEnd);
        setPicked(null);
        window.getSelection()?.removeAllRanges();
      }}
    >
      Add cited case
    </button>,
    document.body,
  );
}
