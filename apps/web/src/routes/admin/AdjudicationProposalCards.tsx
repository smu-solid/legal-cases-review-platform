import type { components } from "../../api/generated/openapi";
import type { AdjudicationWorkspaceItem } from "../../api/types";
import { AdjudicationSubmissionCards } from "./AdjudicationSubmissionCards";

type ReviewerProposal = components["schemas"]["ReviewerProposal"];
type ProposalSpan = components["schemas"]["ProposalSpan"];

export interface AdjudicationProposalCardEntry {
  proposal: ReviewerProposal;
  reviewerKey: string;
  reviewerLabel: string;
  proposalNumber: number;
}

function proposalChoiceLabel(entry: AdjudicationProposalCardEntry) {
  return `${entry.reviewerLabel} · Proposal ${entry.proposalNumber}`;
}

export function AdjudicationProposalCards({
  entries,
  source,
  onNavigate,
  originalItem,
}: {
  originalItem?: AdjudicationWorkspaceItem;
  entries: AdjudicationProposalCardEntry[];
  source: { snapshotId: string; version: string; content: string; snapshotIds?: string[] };
  onNavigate: (span: ProposalSpan, label: string) => void;
}) {
  const reviewers = new Map<string, AdjudicationProposalCardEntry[]>();
  for (const entry of entries) {
    const own = reviewers.get(entry.reviewerKey) ?? [];
    own.push(entry);
    reviewers.set(entry.reviewerKey, own);
  }
  for (const submission of originalItem?.submissions ?? []) {
    const key = submission.reviewer?.email ?? submission.pseudonym;
    if (!reviewers.has(key)) reviewers.set(key, []);
  }
  const labelFor = (key: string, proposals: AdjudicationProposalCardEntry[]) =>
    proposals[0]?.reviewerLabel ??
    originalItem?.submissions.find((s) => (s.reviewer?.email ?? s.pseudonym) === key)?.reviewer
      ?.display_name ??
    key;
  return (
    <div className="submission-grid adjudication-submission-grid">
      {Array.from(reviewers, ([reviewerKey, proposals]) => (
        <article
          className="adjudication-reviewer-card"
          key={reviewerKey}
          aria-label={`${labelFor(reviewerKey, proposals)} proposals`}
        >
          <div className="adjudication-reviewer-heading">
            <strong>{labelFor(reviewerKey, proposals)}</strong>
            <span className="status-chip">Reviewer-added</span>
          </div>
          {originalItem ? (
            <AdjudicationSubmissionCards
              embedded
              sourceContent={source.content}
              item={{
                ...originalItem,
                submissions: originalItem.submissions.filter(
                  (s) => (s.reviewer?.email ?? s.pseudonym) === reviewerKey,
                ),
              }}
            />
          ) : null}
          {proposals.map((entry) => (
            <section key={entry.proposal.id} aria-label={proposalChoiceLabel(entry)}>
              <h4>Proposal {entry.proposalNumber}</h4>
              <div className="correction-box adjudication-reviewer-correction">
                <p>
                  <span>Proposed value</span>
                  <strong>{entry.proposal.value}</strong>
                </p>
                <p>
                  <span>Reviewer note</span>
                  {entry.proposal.note || "No reviewer note."}
                </p>
              </div>
              <div className="evidence-box adjudication-reviewer-provenance">
                <span>Marked supporting provenance</span>
                {(entry.proposal.provenance ?? []).map((span, index) => {
                  const available =
                    (span.source_snapshot_id === source.snapshotId ||
                      source.snapshotIds?.includes(span.source_snapshot_id)) &&
                    span.source_version === source.version &&
                    span.char_start >= 0 &&
                    span.char_end > span.char_start &&
                    span.char_end <= source.content.length;
                  const label = `${proposalChoiceLabel(entry)} · passage ${index + 1}`;
                  return (
                    <div className="provenance-marked-item" key={`${entry.proposal.id}-${index}`}>
                      {available ? (
                        <p className="provenance-marked-text">
                          “{source.content.slice(span.char_start, span.char_end)}”
                        </p>
                      ) : (
                        <p role="status">
                          This passage is unavailable in the current source version.
                        </p>
                      )}
                      <p className="provenance-marked-range">
                        chars {span.char_start}–{span.char_end}
                      </p>
                      <button
                        type="button"
                        className="link-button"
                        disabled={!available}
                        onClick={() => onNavigate(span, label)}
                      >
                        {label} provenance
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </article>
      ))}
    </div>
  );
}

export function AdjudicationProposalPreferences({
  entries,
  selectedId,
  disabled,
  onSelect,
  embedded = false,
}: {
  embedded?: boolean;
  entries: AdjudicationProposalCardEntry[];
  selectedId: string | null;
  disabled: boolean;
  onSelect: (proposalId: string) => void;
}) {
  const Container = embedded ? "div" : "fieldset";
  return (
    <Container className="verdict-option-list">
      {embedded ? null : <legend>Preferred proposal</legend>}
      {entries.map((entry) => (
        <label className="verdict-option" key={entry.proposal.id}>
          <input
            type="radio"
            name="proposal-outcome"
            disabled={disabled}
            checked={selectedId === entry.proposal.id}
            onChange={() => onSelect(entry.proposal.id)}
          />
          <span>
            <strong>{proposalChoiceLabel(entry)} preferred</strong>
            <span>{entry.proposal.value}</span>
          </span>
        </label>
      ))}
    </Container>
  );
}
