import type { GroupItem } from "../../api/types";
import { ExtractedValue } from "../../components/ExtractedValue";
import { InfoTooltip } from "../../components/InfoTooltip";
import { MemberSourceValues } from "../../components/MemberSourceValues";
import { Spinner } from "../../components/Spinner";
import type { BooleanAnswer, LocalAnswer, MutationErrorDescription } from "./reviewerAnswerState";
import { itemStatus } from "./reviewerAnswerState";

function AnswerCorrectionFields({
  answer,
  update,
}: {
  answer: LocalAnswer;
  update: (partial: Partial<LocalAnswer>) => void;
}) {
  return (
    <div className="correction-box">
      <p className="correction-box-title">Correction</p>
      <label>
        Reason
        <select
          value={answer.failure_reason}
          onChange={(event) => update({ failure_reason: event.target.value })}
        >
          <option value="">Select reason</option>
          <option value="value_incorrect">Value is incorrect</option>
          <option value="value_incomplete">Value is incomplete</option>
          <option value="evidence_wrong_location">Evidence points to the wrong place</option>
          <option value="evidence_not_locatable">Evidence cannot be located</option>
          <option value="other">Other (explain in comment)</option>
        </select>
      </label>
      <label>
        Corrected value
        <input
          type="text"
          value={answer.corrected_value}
          onChange={(event) => update({ corrected_value: event.target.value })}
        />
      </label>
      <label>
        Reviewer note
        <textarea
          rows={4}
          value={answer.comment}
          onChange={(event) => update({ comment: event.target.value })}
        />
      </label>
    </div>
  );
}

function AnswerEvidenceFields({
  answer,
  update,
}: {
  answer: LocalAnswer;
  update: (partial: Partial<LocalAnswer>) => void;
}) {
  const sectionToExtract = (
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
  );
  return sectionToExtract;
}

function AnswerToggle({
  label,
  value,
  onChange,
  hint,
  disableYes,
  disabledHint,
}: {
  label: string;
  value: BooleanAnswer;
  onChange: (value: BooleanAnswer) => void;
  hint?: string;
  // When set, the "Yes" option cannot be selected -- used for items with no extracted value,
  // where the backend hard-rejects value_correct=true (missing_value_cannot_be_correct).
  disableYes?: boolean;
  disabledHint?: string;
}) {
  return (
    <fieldset className="toggle-group">
      <legend>
        {label}
        {hint ? <InfoTooltip label={`About: ${label}`} text={hint} /> : null}
      </legend>
      <div className="segmented-control">
        <button
          aria-pressed={value === true}
          className={value === true ? "is-selected" : ""}
          disabled={disableYes}
          title={disableYes ? disabledHint : undefined}
          type="button"
          onClick={() => onChange(true)}
        >
          Yes
        </button>
        <button
          aria-pressed={value === false}
          className={value === false ? "is-selected" : ""}
          type="button"
          onClick={() => onChange(false)}
        >
          No
        </button>
      </div>
    </fieldset>
  );
}

export function AnswerPanel({
  activeItem,
  answer,
  onChange,
  onSave,
  onSubmit,
  isSaving,
  isSubmitting,
  saveError,
  submitError,
  onRefresh,
  pickingProvenance,
  onTogglePicking,
  readOnly = false,
}: {
  activeItem: GroupItem | null;
  answer: LocalAnswer | undefined;
  onChange: (item: GroupItem, answer: LocalAnswer) => void;
  onSave: () => void;
  onSubmit: () => void;
  isSaving: boolean;
  isSubmitting: boolean;
  saveError: MutationErrorDescription | null;
  submitError: MutationErrorDescription | null;
  onRefresh: () => void;
  pickingProvenance: boolean;
  onTogglePicking: () => void;
  readOnly?: boolean;
}) {
  if (!activeItem || !answer) {
    return (
      <section className="answer-pane">
        <h3>Select an item</h3>
        <p>Choose a grouped field to review its value and provenance.</p>
      </section>
    );
  }

  const isMissing = activeItem.extraction_state === "missing";
  const showCorrection = answer.value_correct === false || answer.provenance_correct === false;
  // A value marked incorrect must carry either a corrected value or an explanatory comment --
  // otherwise the reviewer has flagged a problem with nothing for anyone to act on.
  const needsCorrectionOrComment =
    answer.value_correct === false && !answer.corrected_value.trim() && !answer.comment.trim();
  const answered = answer.value_correct !== null && answer.provenance_correct !== null;

  function update(partial: Partial<LocalAnswer>) {
    if (answer?.submitted || readOnly) return;
    onChange(activeItem!, { ...answer!, saved: false, submitted: false, ...partial });
  }

  return (
    <section className="answer-pane" aria-labelledby="answer-title">
      <fieldset
        disabled={answer.submitted || readOnly}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0, display: "grid", gap: 12 }}
      >
        {/* One heading row: the field label beside its status chip. The former item_kind eyebrow
          ("CITED CASE" above "Cited case") duplicated the label for every relation field and is
          deliberately gone. */}
        <div className="pane-heading answer-heading">
          <h3 id="answer-title">{activeItem.item_label}</h3>
          <span className="status-chip">
            <span
              aria-hidden="true"
              className={`status-dot status-dot-${itemStatus(answer).kind}`}
            />
            {itemStatus(answer).label}
          </span>
        </div>

        <ExtractedValue value={activeItem.extracted_value_display} missing={isMissing} />
        <MemberSourceValues
          values={activeItem.member_values ?? []}
          disagreement={activeItem.cross_source_disagreement ?? false}
        />

        <AnswerToggle
          label="Is the extracted value correct?"
          value={answer.value_correct}
          hint="Compare the value above against the highlighted source on the right."
          disableYes={isMissing}
          disabledHint="No value was extracted for this field, so it cannot be marked correct. Enter the correct value below."
          onChange={(value) => {
            // "Yes" is unreachable for a missing item (button disabled above), but guard here too so
            // no code path can smuggle value_correct=true past the server's hard rejection.
            const nextValue = isMissing ? false : value;
            update({
              value_correct: nextValue,
              provenance_correct: nextValue === false ? false : answer.provenance_correct,
              failure_reason: answer.failure_reason,
            });
          }}
        />
        <AnswerToggle
          label="Is the highlighted provenance correct?"
          value={answer.provenance_correct}
          hint="Does the highlighted span in the source actually support this value? If not, mark the correct span in the source pane."
          disableYes={isMissing}
          disabledHint="Nothing was extracted, so there is no provenance to affirm. Mark the correct provenance span for the value you enter."
          // Missing items have no extracted provenance to affirm -- lock this control to No too, so the
          // reviewer supplies the correct provenance for the value they enter.
          onChange={(value) =>
            update({
              provenance_correct: isMissing ? false : value,
              failure_reason: answer.failure_reason,
            })
          }
        />

        {/* Reason -> corrected value -> comment lives directly under the No toggles, above the
          provenance-marking action below, so the reviewer sees "what's wrong and what it should
          be" before the separate in-source provenance-marking workflow. */}
        {showCorrection ? <AnswerCorrectionFields {...{ answer, update }} /> : null}

        {}
        {answer.provenance_correct === false ? (
          <div className="provenance-correction-action">
            <button
              type="button"
              className={pickingProvenance ? "primary-button is-active" : "primary-button"}
              onClick={onTogglePicking}
              disabled={!activeItem.evidence_window_ids.length}
            >
              {pickingProvenance ? "Cancel marking (Esc)" : "Mark corrected provenance in source"}
            </button>
            <p className="provenance-pick-guidance">
              Select the text in the source that supports the corrected value/evidence.
            </p>
          </div>
        ) : null}

        {answer.corrected_provenance_spans.length > 0 ? (
          <AnswerEvidenceFields {...{ answer, update }} />
        ) : null}

        {saveError ? (
          <div className="notice compact" role="alert">
            {saveError.message}
            {saveError.isStale ? (
              <button type="button" className="link-button" onClick={onRefresh}>
                Refresh and retry
              </button>
            ) : null}
          </div>
        ) : null}
        {submitError ? (
          <div className="notice compact" role="alert">
            {submitError.message}
            {submitError.isStale ? (
              <button type="button" className="link-button" onClick={onRefresh}>
                Refresh and retry
              </button>
            ) : null}
          </div>
        ) : null}
        {answered && needsCorrectionOrComment ? (
          <div className="notice compact" role="status">
            Add a corrected value or a comment before submitting an incorrect value.
          </div>
        ) : null}

        <div className="action-row">
          <button className="secondary-button" type="button" disabled={isSaving} onClick={onSave}>
            {isSaving ? (
              <>
                <Spinner /> Saving...
              </>
            ) : (
              "Save draft"
            )}
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={isSubmitting || !answered || needsCorrectionOrComment}
            onClick={onSubmit}
          >
            {isSubmitting ? (
              <>
                <Spinner /> Submitting...
              </>
            ) : (
              "Submit field"
            )}
          </button>
        </div>
      </fieldset>
    </section>
  );
}
