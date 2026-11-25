import type { CitationFeedback } from "./useCitationDuplicates";

export function CitationDuplicateFeedback({
  feedback,
  onOpen,
  busy = false,
}: {
  busy?: boolean;
  feedback: CitationFeedback;
  onOpen: (id: string) => void;
}) {
  if (!feedback.enabled) return null;
  return (
    <div className="citation-duplicate-feedback" aria-live="polite">
      {feedback.error && <p role="alert">{feedback.error}</p>}
      {feedback.data?.conflicts?.map((conflict) => (
        <div className="notice compact" key={conflict.item_id}>
          Duplication detected,{" "}
          <button
            type="button"
            className="link-button"
            aria-label={`Click here to view the existing citation: ${conflict.value}`}
            disabled={busy}
            onClick={() => onOpen(conflict.item_id)}
          >
            click here to view the existing citation
          </button>
        </div>
      ))}
    </div>
  );
}
