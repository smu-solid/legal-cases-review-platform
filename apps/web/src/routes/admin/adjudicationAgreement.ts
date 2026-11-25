import type { AdjudicationGroupedItem, AdjudicationWorkspaceItem } from "../../api/types";

export type AgreementStatus =
  | "disagreement"
  | "positive_agreement"
  | "negative_agreement"
  | "value_provenance_disagreement"
  | "all"
  | "reviewer_added";

export const agreementFilterOptions: ReadonlyArray<{
  value: AgreementStatus;
  label: string;
}> = [
  { value: "disagreement", label: "Disagreement" },
  { value: "positive_agreement", label: "Positive agreement" },
  { value: "negative_agreement", label: "Negative agreement" },
  { value: "value_provenance_disagreement", label: "Value/provenance disagreement" },
  { value: "all", label: "All" },
  { value: "reviewer_added", label: "Reviewer-added" },
];

export function agreementStatus(
  item: AdjudicationGroupedItem | AdjudicationWorkspaceItem,
): AgreementStatus | null {
  if ("proposal_item" in item && item.proposal_item) return null;
  const requiredReviews = item.required_reviews ?? item.submissions.length;
  if (item.submissions.length < requiredReviews) return null;

  const allPositive = item.submissions.every(
    (submission) => submission.value_correct && submission.provenance_correct,
  );
  if (allPositive) return "positive_agreement";

  const allNegative = item.submissions.every(
    (submission) => !submission.value_correct && !submission.provenance_correct,
  );
  if (allNegative) return "negative_agreement";

  const first = item.submissions[0];
  const unanimousMixed = item.submissions.every(
    (submission) =>
      submission.value_correct === first.value_correct &&
      submission.provenance_correct === first.provenance_correct,
  );
  return unanimousMixed ? "value_provenance_disagreement" : "disagreement";
}

export function matchesAgreementFilter(
  item: AdjudicationGroupedItem | AdjudicationWorkspaceItem,
  filter: AgreementStatus,
) {
  return (
    filter === "all" ||
    (filter === "reviewer_added"
      ? "proposal_item" in item && Boolean(item.proposal_item)
      : agreementStatus(item) === filter)
  );
}
