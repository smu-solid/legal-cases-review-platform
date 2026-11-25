import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

// Compact "info icon" helper: opens on hover/focus/click to reveal a short explanation. Shared by
// the admin and reviewer surfaces to keep helper documentation off the main form while staying
// discoverable. Positioned with `position: fixed` (computed from the button's own rect) rather than
// CSS-anchored, so it never overflows a narrow right-side panel or covers the controls below it.
const POPOVER_GAP = 8;
const VIEWPORT_MARGIN = 8;
const MAX_POPOVER_WIDTH = 280;

export function InfoTooltip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [style, setStyle] = useState<{
    position: "fixed";
    top: number;
    left: number;
    maxWidth: number;
  }>();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();

  const close = () => {
    setOpen(false);
    setPinned(false);
  };

  // Measure after the popover has rendered so real content height/width drive placement.
  useLayoutEffect(() => {
    if (!open) return;
    const button = buttonRef.current;
    const popover = popoverRef.current;
    if (!button || !popover) return;

    const buttonRect = button.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    const maxWidth = Math.min(MAX_POPOVER_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2);

    const fitsAbove = buttonRect.top - popoverRect.height - POPOVER_GAP >= VIEWPORT_MARGIN;
    const top = fitsAbove
      ? buttonRect.top - popoverRect.height - POPOVER_GAP
      : buttonRect.bottom + POPOVER_GAP;

    const left = Math.min(
      Math.max(buttonRect.left, VIEWPORT_MARGIN),
      window.innerWidth - popoverRect.width - VIEWPORT_MARGIN,
    );

    setStyle({ position: "fixed", top, left, maxWidth });
  }, [open]);

  // Any scroll can move the icon out from under a fixed-position popover (including nested scroll
  // containers), and we don't reposition on scroll -- so just close it instead of letting it drift.
  useEffect(() => {
    if (!open) return;
    const handleDismiss = () => close();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("scroll", handleDismiss, true);
    window.addEventListener("resize", handleDismiss);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("scroll", handleDismiss, true);
      window.removeEventListener("resize", handleDismiss);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <span className="info-tooltip">
      <button
        ref={buttonRef}
        type="button"
        className="info-tooltip-button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? tooltipId : undefined}
        onClick={() => {
          setPinned((current) => {
            const nextPinned = !current || !open;
            setOpen(nextPinned);
            return nextPinned;
          });
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => {
          if (!pinned) setOpen(false);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => close()}
      >
        i
      </button>
      {open ? (
        <span
          ref={popoverRef}
          id={tooltipId}
          className="info-tooltip-popover"
          role="tooltip"
          style={style}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}
