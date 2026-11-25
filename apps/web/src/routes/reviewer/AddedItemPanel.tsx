import { useEffect, useRef } from "react";
import type { GroupItem } from "../../api/types";
import { CitationDuplicateFeedback } from "./CitationDuplicateFeedback";
import "./reviewerAdditions.css";
import type { LocalAnswer, MutationErrorDescription } from "./reviewerAnswerState";
import { proposalReady } from "./reviewerProposals";
import type { CitationFeedback } from "./useCitationDuplicates";

const REQUIRED = "Marking supporting provenance is compulsory before submitting an added item.";

export function AddedItemPanel({
  item,
  answer,
  onChange,
  onSave,
  onSubmit,
  onRemove,
  picking,
  onTogglePicking,
  busy,
  error,
  readOnly,
  onRefresh,
  duplicateFeedback,
  onOpenExisting,
}: {
  duplicateFeedback?: CitationFeedback;
  onOpenExisting?: (id: string) => void;
  item: GroupItem;
  answer: LocalAnswer;
  onChange: (item: GroupItem, answer: LocalAnswer) => void;
  onSave: () => void;
  onSubmit: () => void;
  onRemove: () => void;
  picking: boolean;
  onTogglePicking: () => void;
  busy: boolean;
  error: MutationErrorDescription | null;
  readOnly: boolean;
  onRefresh?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!readOnly) input.current?.focus();
  }, [item.review_unit_id, readOnly]);
  const locked = readOnly || answer.submitted;
  const missingProvenance = answer.corrected_provenance_spans.length === 0;
  const duplicated = duplicateFeedback?.data?.conflicts?.some((c) => c.kind === "confirmed");
  function update(patch: Partial<LocalAnswer>) {
    if (!locked) onChange(item, { ...answer, ...patch, saved: false });
  }
  return (
    <section className="answer-pane added-item-pane" aria-label="Reviewer-added item editor">
      <fieldset disabled={locked || busy} className="added-item-fields">
        <label>
          Proposed value
          <input
            ref={input}
            value={answer.corrected_value}
            maxLength={10000}
            placeholder={
              item.reviewer_proposal?.group_id === "statutes_cited"
                ? "Statute name and provision, if applicable"
                : "Case citation and name"
            }
            onChange={(event) => update({ corrected_value: event.target.value })}
          />
        </label>
        <label>
          Reviewer note (optional)
          <textarea
            rows={4}
            value={answer.comment}
            maxLength={10000}
            onChange={(event) => update({ comment: event.target.value })}
          />
        </label>
        <div className="provenance-correction-action">
          <button
            type="button"
            className={picking ? "primary-button is-active" : "primary-button"}
            onClick={onTogglePicking}
          >
            {picking ? "Cancel marking (Esc)" : "Mark provenance in source"}
          </button>
          <p className="provenance-pick-guidance" id="added-submit-explanation">
            Select the source text that supports the proposed value.{" "}
            {missingProvenance && <>{REQUIRED} </>}You may save an incomplete draft.
          </p>
        </div>
        {answer.corrected_provenance_spans.length > 0 ? (
          <div className="evidence-box">
            <span>Your marked provenance</span>
            {answer.corrected_provenance_spans.map((span, index) => {
              const snippet = span.selected_text?.trim() ?? "";
              const truncated = snippet.length > 120 ? `${snippet.slice(0, 120)}…` : snippet;
              return (
                <div className="provenance-marked-item" key={`${span.char_start}-${span.char_end}`}>
                  {snippet ? (
                    <p className="provenance-marked-text" title={snippet}>
                      “{truncated}”
                    </p>
                  ) : null}
                  <p className="provenance-marked-row">
                    <span className="provenance-marked-range">
                      chars {span.char_start}–{span.char_end}
                    </span>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() =>
                        update({
                          corrected_provenance_spans: answer.corrected_provenance_spans.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      clear
                    </button>
                  </p>
                </div>
              );
            })}
          </div>
        ) : null}
      </fieldset>
      {!locked && duplicateFeedback && onOpenExisting && (
        <CitationDuplicateFeedback
          busy={busy}
          feedback={duplicateFeedback}
          onOpen={onOpenExisting}
        />
      )}
      {locked ? (
        <p role="status">Submitted work is read-only.</p>
      ) : (
        <>
          <div className="action-row">
            <button type="button" className="secondary-button" disabled={busy} onClick={onSave}>
              Save draft
            </button>
            <span
              className="added-submit-hint"
              tabIndex={missingProvenance ? 0 : undefined}
              aria-describedby="added-submit-explanation"
              title={missingProvenance ? REQUIRED : undefined}
            >
              <button
                type="button"
                className="primary-button"
                aria-describedby="added-submit-explanation"
                disabled={busy || !proposalReady(answer) || duplicated}
                onClick={onSubmit}
              >
                Submit field
              </button>
              {missingProvenance && <span role="tooltip">{REQUIRED}</span>}
            </span>
          </div>
          <button type="button" className="link-button" disabled={busy} onClick={onRemove}>
            Remove unsubmitted addition
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="notice">
          {error.message}
          {error.isStale && onRefresh ? (
            <button type="button" className="link-button" onClick={onRefresh}>
              Refresh and retry
            </button>
          ) : null}
        </p>
      )}
    </section>
  );
}
