import { ExtractedValue } from "../../components/ExtractedValue";
import type { DecisionPaneProps } from "./AdjudicationDecisionPane";
import {
  AdjudicationProposalCards,
  AdjudicationProposalPreferences,
} from "./AdjudicationProposalCards";
import { AdjudicationProvenanceControls } from "./AdjudicationProvenanceControls";
import { adjudicationReviewerLabel } from "./adjudicationReviewerLabel";

export function ProposalDecisionPanel(props: DecisionPaneProps) {
  const item = props.activeItem!;
  const proposal = item.proposal_item!;
  const entries = proposal.proposals.map((p) => ({
    proposal: p,
    reviewerKey: p.reviewer_key,
    reviewerLabel: p.reviewer_label,
    proposalNumber: p.proposal_number,
  }));
  const reviewers = new Set([
    ...proposal.proposals.map((p) => p.reviewer_key),
    ...item.submissions.map((s) => s.reviewer?.email ?? s.pseudonym),
  ]);
  return (
    <section
      className="answer-pane adjudication-decision-pane"
      aria-label="Reviewer-added adjudication"
    >
      <div className="pane-heading">
        <h3>{item.item_label}</h3>
        <span className="status-chip">Reviewer-added</span>
      </div>
      <p>
        {proposal.proposals.length} proposals from {reviewers.size}{" "}
        {reviewers.size === 1 ? "reviewer" : "reviewers"}
      </p>
      <p>
        {proposal.origin === "combined"
          ? "Manually combined"
          : proposal.origin === "separated"
            ? "Kept separate"
            : proposal.proposals.length === 1
              ? "One proposal; absence from another reviewer is not rejection."
              : proposal.matching_reasons.includes("normalized_value")
                ? "Matching normalized values"
                : "Matching complete provenance span sets"}
        {proposal.different_values ? " · Different proposed values" : ""}
      </p>
      <p className="muted">
        Grouping organizes comparison. It does not accept an item or establish agreement.
      </p>
      {props.proposalControls}
      {proposal.extracted_adjudication_id ? (
        <ExtractedValue
          value={item.extracted_value_display}
          missing={item.extracted_value_display === "No value extracted"}
        />
      ) : null}
      <AdjudicationProposalCards
        entries={entries}
        source={{ ...item.proposal_source!, content: props.sourceContent }}
        originalItem={proposal.extracted_adjudication_id ? item : undefined}
        onNavigate={(span, label) => props.onShowProposalSpan?.(span, label)}
      />
      <fieldset className="verdict-option-list" disabled={!props.editable}>
        <legend>Final decision</legend>
        <AdjudicationProposalPreferences
          embedded
          entries={entries}
          disabled={!props.editable}
          selectedId={props.verdict?.startsWith("proposal:") ? props.verdict.slice(9) : null}
          onSelect={(id) => props.onVerdictChange(`proposal:${id}`)}
        />
        {item.submissions.map((s) => (
          <label className="verdict-option" key={s.submission_id}>
            <input
              type="radio"
              name="proposal-outcome"
              checked={props.verdict === `preferred:${s.submission_id}`}
              onChange={() => props.onVerdictChange(`preferred:${s.submission_id}`)}
            />
            <span>
              {adjudicationReviewerLabel(s)} · Original submission preferred:{" "}
              {s.corrected_value_display || item.extracted_value_display}
            </span>
          </label>
        ))}
        {(
          [
            ["all_equivalent_supported", "All equivalent / supported"],
            ["all_wrong", "All wrong / enter a correction"],
            ["unsupported_or_not_locatable", "Reject — unsupported / not locatable"],
            ["exceptional_skip", "Skip (exceptional)"],
          ] as const
        ).map(([value, label]) => (
          <label className="verdict-option" key={value}>
            <input
              type="radio"
              name="proposal-outcome"
              checked={props.verdict === value}
              onChange={() => props.onVerdictChange(value)}
            />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>
      <label>
        Corrected final value, if needed
        <input
          value={props.correctedValue}
          disabled={!props.editable}
          onChange={(e) => props.onCorrectedValueChange(e.target.value)}
        />
      </label>
      <AdjudicationProvenanceControls {...props} />
      <label>
        Adjudicator note
        <textarea
          rows={4}
          value={props.comment}
          disabled={!props.editable}
          onChange={(e) => props.onCommentChange(e.target.value)}
        />
      </label>
      {props.correctedValue.trim() &&
      ["unsupported_or_not_locatable", "exceptional_skip"].includes(props.verdict ?? "") ? (
        <p role="alert">
          Clear the corrected value to reject this item, or choose a value decision.
        </p>
      ) : null}
      {props.saveError || props.submitError ? (
        <div className="notice" role="alert">
          The write was rejected. Your unsaved input is retained. Refresh and reassess if membership
          changed.
        </div>
      ) : null}
      {props.saveSuccess ? <p role="status">Draft saved.</p> : null}
      {props.editable ? (
        <div className="adjudication-decision-actions">
          <button
            type="button"
            className="secondary-button"
            disabled={!props.canSave || props.saving}
            onClick={props.onSave}
          >
            Save draft
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={!props.canSubmit || props.submitting}
            onClick={props.onSubmit}
          >
            Submit adjudication
          </button>
        </div>
      ) : (
        <div className="notice">
          Submitted decision · read-only
          {proposal.final_value ? <p>Final value: {proposal.final_value}</p> : null}
        </div>
      )}
    </section>
  );
}
