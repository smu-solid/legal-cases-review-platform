import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

interface CaseSubmitLocationState {
  caseSubmitToast?: string;
}

// A brief, self-dismissing success banner surfaced via router navigation state after a final case
// submit auto-navigates the reviewer forward (see ReviewerWorkspacePage's confirmCaseSubmit).
//
// Keyed off `location.key` (React Router's unique id per navigation entry) rather than "on mount"
// alone: the case workspace route (`/review/task/:assignmentId`) reuses the same component instance
// across a same-route navigation (submitting case A auto-navigates to case B without unmounting), so
// a plain mount-only read would miss a toast set by that later navigate() call. Each time the key
// changes, a pending toast is picked up into local state and immediately stripped from history state
// (so a refresh or back-navigation never resurfaces it) while staying in local state long enough for
// the dismiss timer below to clear it from the screen.
export function useCaseSubmitToast(durationMs = 4000): string | null {
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const toast = (location.state as CaseSubmitLocationState | null)?.caseSubmitToast ?? null;
    if (!toast) {
      return;
    }
    setMessage(toast);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: {} });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  useEffect(() => {
    if (!message) {
      return;
    }
    const timer = setTimeout(() => setMessage(null), durationMs);
    return () => clearTimeout(timer);
  }, [message, durationMs]);

  return message;
}
