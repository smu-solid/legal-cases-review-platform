import { useEffect } from "react";

export function useReviewerKeyboard(actions: {
  step: (direction: 1 | -1) => void;
  nextGroup: () => void;
  value: (value: boolean) => void;
  provenance: (value: boolean) => void;
  save: () => void;
  submit: () => void;
  mark: () => void;
  help: () => void;
  escape: () => void;
  ready: boolean;
  editable: boolean;
  added: boolean;
  modalOpen: boolean;
}) {
  useEffect(() => {
    function handle(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (event.repeat) {
        if (event.key === "Enter" && !target?.closest('input, textarea, [contenteditable="true"]'))
          event.preventDefault();
        return;
      }
      if (event.key === "Escape") {
        actions.escape();
        return;
      }
      if (
        event.key === "?" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !target?.closest("input, textarea, select, [contenteditable=true]")
      ) {
        actions.help();
        return;
      }
      if (actions.modalOpen || target?.closest('[role="dialog"]')) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (actions.editable) actions.save();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]'))
        return;
      // Native button/link activation owns Enter; never also submit the active field.
      if (event.key === "Enter" && target?.closest('button, a, [role="button"]')) return;
      switch (event.key) {
        case "j":
        case "ArrowDown":
          event.preventDefault();
          actions.step(1);
          break;
        case "k":
        case "ArrowUp":
          event.preventDefault();
          actions.step(-1);
          break;
        case "g":
          actions.nextGroup();
          break;
        case "1":
        case "2":
          if (actions.editable && !actions.added) actions.value(event.key === "1");
          break;
        case "3":
        case "4":
          if (actions.editable && !actions.added) actions.provenance(event.key === "3");
          break;
        case "m":
          if (actions.editable) actions.mark();
          break;
        case "s":
          if (actions.editable) actions.save();
          break;
        case "Enter":
          if (actions.editable && actions.ready) {
            event.preventDefault();
            actions.submit();
          }
          break;
        case "?":
          actions.help();
          break;
      }
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [actions]);
}
