import { useRef, useState } from "react";
import { useBlocker } from "react-router-dom";

export function ReviewerLeaveGuard({ dirty, save }: { dirty: boolean; save: () => Promise<void> }) {
  const blocker = useBlocker(dirty);
  const working = useRef(false);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  async function leave() {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError(false);
    try {
      await save();
      blocker.proceed?.();
    } catch {
      setError(true);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  if (blocker.state !== "blocked") return null;
  return (
    <div className="modal-backdrop">
      <section
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="leave-review-title"
      >
        <h3 id="leave-review-title">Save your drafts before leaving</h3>
        <p>Your unfinished additions and field edits are still here.</p>
        {error && (
          <p role="alert">
            Drafts could not be saved. Stay here and retry; your changes have been kept.
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => blocker.reset?.()}
          >
            Stay and edit
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={busy}
            onClick={() => void leave()}
          >
            Save drafts and leave
          </button>
        </div>
      </section>
    </div>
  );
}
