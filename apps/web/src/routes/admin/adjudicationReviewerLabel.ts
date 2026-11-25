import type { AdjudicationWorkspaceItem } from "../../api/types";

type Submission = AdjudicationWorkspaceItem["submissions"][number];

export function adjudicationReviewerLabel(submission: Submission) {
  return (
    submission.reviewer?.display_name?.trim() || submission.reviewer?.email || submission.pseudonym
  );
}
