import type { AdjudicationWorkspaceItem } from "../../api/types";

import { adjudicationReviewerLabel } from "./adjudicationReviewerLabel";

const FAILURE_REASON_LABELS: Record<string, string> = {
  value_incorrect: "Value is incorrect",
  value_incomplete: "Value is incomplete",
  evidence_wrong_location: "Evidence points to the wrong place",
  evidence_not_locatable: "Evidence cannot be located",
  other: "Other",
};

export function AdjudicationSubmissionCards({
  item,
  sourceContent,
  embedded = false,
}: {
  item: AdjudicationWorkspaceItem;
  sourceContent: string;
  embedded?: boolean;
}) {
  const Card = embedded ? "div" : "article";
  return (
    <div className="submission-grid adjudication-submission-grid">
      {item.submissions.map((submission) => (
        <Card
          className={embedded ? undefined : "adjudication-reviewer-card"}
          key={submission.submission_id}
        >
          <div className="adjudication-reviewer-heading">
            <strong title={submission.reviewer?.email ?? undefined}>
              {adjudicationReviewerLabel(submission)}
            </strong>
            <time dateTime={submission.submitted_at}>
              {new Date(submission.submitted_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
          </div>
          <dl className="adjudication-correctness-grid">
            <div>
              <dt>Value correct:</dt>
              <dd className={submission.value_correct ? "answer-badge yes" : "answer-badge no"}>
                {submission.value_correct ? "YES" : "NO"}
              </dd>
            </div>
            <div>
              <dt>Provenance correct:</dt>
              <dd
                className={submission.provenance_correct ? "answer-badge yes" : "answer-badge no"}
              >
                {submission.provenance_correct ? "YES" : "NO"}
              </dd>
            </div>
          </dl>
          {!submission.value_correct || !submission.provenance_correct ? (
            <div className="correction-box adjudication-reviewer-correction">
              <p className="correction-box-title">Correction</p>
              {submission.failure_reason ? (
                <p>
                  <span>Reason</span>
                  <strong>
                    {FAILURE_REASON_LABELS[submission.failure_reason] ?? submission.failure_reason}
                  </strong>
                </p>
              ) : null}
              {submission.corrected_value_display ? (
                <p>
                  <span>Corrected value</span>
                  <strong>{submission.corrected_value_display}</strong>
                </p>
              ) : null}
              <p>
                <span>Reviewer note</span>
                {submission.comment ? `“${submission.comment}”` : "No reviewer comment."}
              </p>
            </div>
          ) : submission.comment ? (
            <p>“{submission.comment}”</p>
          ) : null}
          {submission.corrected_provenance_spans?.length ? (
            <div className="evidence-box adjudication-reviewer-provenance">
              <span>Reviewer marked provenance</span>
              {(submission.corrected_provenance_spans ?? []).map((span) => {
                const snippet = sourceContent.slice(span.char_start, span.char_end).trim();
                const truncated = snippet.length > 120 ? `${snippet.slice(0, 120)}…` : snippet;
                return (
                  <div
                    className="provenance-marked-item"
                    key={`${span.evidence_window_id}-${span.char_start}-${span.char_end}`}
                  >
                    {truncated ? (
                      <p className="provenance-marked-text" title={snippet}>
                        “{truncated}”
                      </p>
                    ) : null}
                    <p className="provenance-marked-range">
                      chars {span.char_start}–{span.char_end}
                    </p>
                  </div>
                );
              })}
            </div>
          ) : null}
        </Card>
      ))}
    </div>
  );
}
