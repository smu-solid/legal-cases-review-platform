import type { ReactNode } from "react";
import type { ProposalSpan } from "../../api/proposalAdjudication";
import type { AdjudicationWorkspaceItem } from "../../api/types";
import { ExtractedValue } from "../../components/ExtractedValue";
import type { LocalAdjudicationSpan, Verdict } from "./adjudicationDecisionState";
import { AdjudicationProvenanceControls } from "./AdjudicationProvenanceControls";
import { adjudicationReviewerLabel } from "./adjudicationReviewerLabel";
import { AdjudicationSubmissionCards } from "./AdjudicationSubmissionCards";
import { ProposalDecisionPanel } from "./ProposalDecisionPanel";

const fixedVerdicts = [
  ["all_equivalent_supported", "All equivalent / supported"],
  ["all_wrong", "All wrong"],
  ["unsupported_or_not_locatable", "Unsupported / not locatable"],
  ["exceptional_skip", "Skip (exceptional)"],
] as const;

export type DecisionPaneProps = {
  proposalControls?: ReactNode;
  onShowProposalSpan?: (span: ProposalSpan, label: string) => void;
  activeItem: AdjudicationWorkspaceItem | null;
  sourceContent: string;
  editable: boolean;
  verdict: Verdict | null;
  correctedValue: string;
  comment: string;
  correctedProvenanceSpans: LocalAdjudicationSpan[];
  pickingProvenance: boolean;
  commentRequired: boolean;
  canSave: boolean;
  canSubmit: boolean;
  saving: boolean;
  saveError: boolean;
  saveSuccess: boolean;
  submitting: boolean;
  submitError: boolean;
  onVerdictChange: (verdict: Verdict) => void;
  onCorrectedValueChange: (value: string) => void;
  onCommentChange: (value: string) => void;
  onToggleProvenancePicking: () => void;
  onClearProvenance: (index: number) => void;
  onSave: () => void;
  onSubmit: () => void;
};

export function AdjudicationDecisionPane(props: DecisionPaneProps) {
  if (props.activeItem?.proposal_item) return <ProposalDecisionPanel {...props} />;
  const submissions = props.activeItem?.submissions ?? [];
  return (
    <section className="answer-pane adjudication-decision-pane" aria-labelledby="comparison-title">
      <div className="pane-heading">
        <div>
          <p className="eyebrow">{props.activeItem?.item_kind ?? "Review item"}</p>
          <h3 id="comparison-title">{props.activeItem?.item_label ?? "Select an item"}</h3>
        </div>
        {props.activeItem ? (
          <span className="status-chip">{props.activeItem.participation_status}</span>
        ) : null}
      </div>
      {props.activeItem ? (
        <>
          <ExtractedValue
            value={props.activeItem.extracted_value_display}
            missing={props.activeItem.extracted_value_display === "No value extracted"}
          />
          <AdjudicationSubmissionCards
            item={props.activeItem}
            sourceContent={props.sourceContent}
          />
          <fieldset className="verdict-option-list" disabled={!props.editable}>
            <legend>Final decision</legend>
            {submissions.map((submission) => (
              <label
                className={
                  props.verdict === `preferred:${submission.submission_id}`
                    ? "verdict-option is-selected"
                    : "verdict-option"
                }
                key={submission.submission_id}
              >
                <input
                  type="radio"
                  name="outcome"
                  checked={props.verdict === `preferred:${submission.submission_id}`}
                  onChange={() => props.onVerdictChange(`preferred:${submission.submission_id}`)}
                />
                <span>
                  <strong>{adjudicationReviewerLabel(submission)} preferred</strong>
                </span>
              </label>
            ))}
            {fixedVerdicts.map(([value, label]) => (
              <label
                className={
                  props.verdict === value ? "verdict-option is-selected" : "verdict-option"
                }
                key={value}
              >
                <input
                  type="radio"
                  name="outcome"
                  checked={props.verdict === value}
                  onChange={() => props.onVerdictChange(value)}
                />
                <span>
                  <strong>{label}</strong>
                </span>
              </label>
            ))}
          </fieldset>
        </>
      ) : (
        <p>No item selected.</p>
      )}
      <label>
        Corrected value, if needed
        <input
          type="text"
          disabled={!props.editable}
          value={props.correctedValue}
          onChange={(event) => props.onCorrectedValueChange(event.target.value)}
        />
      </label>
      <AdjudicationProvenanceControls {...props} />
      <label>
        Adjudicator note{props.commentRequired ? " (required)" : ""}
        <textarea
          rows={5}
          disabled={!props.editable}
          value={props.comment}
          onChange={(event) => props.onCommentChange(event.target.value)}
        />
      </label>
      {props.saveError ? <Notice kind="error">The draft could not be saved.</Notice> : null}
      {props.saveSuccess ? <Notice kind="status">Draft saved.</Notice> : null}
      {props.submitError ? (
        <Notice kind="error">
          The decision was rejected. Refresh to recover from changed case state.
        </Notice>
      ) : null}
      {props.editable ? (
        <div className="adjudication-decision-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={!props.canSave || props.saving}
            onClick={props.onSave}
          >
            {props.saving ? "Saving..." : "Save draft"}
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={!props.canSubmit || props.submitting}
            onClick={props.onSubmit}
          >
            {props.submitting ? "Submitting..." : "Submit adjudication"}
          </button>
        </div>
      ) : (
        <div className="notice compact">This finished adjudication is read-only.</div>
      )}
    </section>
  );
}

function Notice({ children, kind }: { children: string; kind: "error" | "status" }) {
  return (
    <div className="notice compact" role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
