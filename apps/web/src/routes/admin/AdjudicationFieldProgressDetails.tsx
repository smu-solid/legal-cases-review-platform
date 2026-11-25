import type { AdjudicationCampaignCaseItem } from "../../api/types";

type FieldProgress = AdjudicationCampaignCaseItem["field_progress"][number];

const stateLabels: Record<FieldProgress["state"], string> = {
  awaiting_reviews: "Awaiting reviews",
  ready_for_adjudication: "Ready for adjudication",
  adjudicated_by_me: "Adjudicated by you",
  not_assigned_to_me: "Not assigned to you",
  unavailable: "Unavailable",
};

type PendingReviewer = NonNullable<FieldProgress["pending_reviewers"]>[number];

function reviewerLabel(reviewer: PendingReviewer) {
  return reviewer.display_name?.trim() || reviewer.email;
}

function FieldState({ field }: { field: FieldProgress }) {
  const pending = field.submitted_reviews > 0 ? (field.pending_reviewers ?? []) : [];
  if (field.state !== "awaiting_reviews" || !pending.length) {
    return <>{stateLabels[field.state]}</>;
  }
  const labels = pending.map(reviewerLabel);
  return (
    <span
      className={labels.length > 1 ? "pending-reviewer-list is-multiple" : "pending-reviewer-list"}
      aria-label={`Waiting for ${labels.join(", ")}`}
      title={`Waiting for ${labels.join(", ")}`}
    >
      <span>Waiting for</span>
      {pending.map((reviewer) => (
        <span className="pending-reviewer-name" key={reviewer.email}>
          {reviewerLabel(reviewer)}
        </span>
      ))}
    </span>
  );
}

function summary(item: AdjudicationCampaignCaseItem) {
  const counts = (item.field_progress ?? []).reduce(
    (result, field) => {
      result[field.state] += 1;
      return result;
    },
    {
      awaiting_reviews: 0,
      ready_for_adjudication: 0,
      adjudicated_by_me: 0,
      not_assigned_to_me: 0,
      unavailable: 0,
    },
  );
  return [
    counts.ready_for_adjudication ? `${counts.ready_for_adjudication} ready` : null,
    counts.awaiting_reviews ? `${counts.awaiting_reviews} awaiting reviews` : null,
    counts.adjudicated_by_me ? `${counts.adjudicated_by_me} adjudicated by you` : null,
    counts.not_assigned_to_me ? `${counts.not_assigned_to_me} not assigned to you` : null,
    counts.unavailable ? `${counts.unavailable} unavailable` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function AdjudicationFieldProgressDetails({ item }: { item: AdjudicationCampaignCaseItem }) {
  const fields = item.field_progress ?? [];
  if (!fields.length) return null;

  return (
    <details className="adjudication-progress-details">
      <summary>Show field progress</summary>
      <p className="adjudication-field-summary">{summary(item)}</p>
      <div className="adjudication-field-progress-table-wrap">
        <table className="adjudication-field-progress-table">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Reviewer progress</th>
              <th scope="col">Adjudication status</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.review_unit_id}>
                <th scope="row">{field.item_label}</th>
                <td>
                  {field.submitted_reviews}/{field.required_reviews} reviews
                </td>
                <td>
                  <span className={`field-progress-state state-${field.state}`}>
                    <FieldState field={field} />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
