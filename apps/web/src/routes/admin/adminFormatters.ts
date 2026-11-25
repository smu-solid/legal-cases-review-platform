import { ApiError } from "../../api/client";
import type {
  AllocationPreviewResponse,
  AllocationPublishResponse,
  AssignmentCounts,
  IncrementalPreviewResponse,
  IncrementalPublishResponse,
  TenantReviewerRosterItem,
} from "../../api/types";

export function reviewerLabel(reviewer: TenantReviewerRosterItem) {
  return `${reviewer.display_name} (${reviewer.user_id.slice(0, 8)})`;
}

export function assignmentPreviewStatusLabel(
  status:
    | AllocationPreviewResponse["feasibility"]["status"]
    | IncrementalPreviewResponse["feasibility"]["status"],
): string {
  switch (status) {
    case "feasible":
      return "Ready to publish";
    case "feasible_with_warnings":
      return "Ready to publish (with warnings)";
    case "blocked_by_reviewer_pool":
      return "Add more reviewers";
    case "blocked_by_capacity":
      return "Increase reviewer capacity";
    case "blocked_by_immutable_work":
      return "Existing reviewer work cannot be moved";
    case "blocked_by_snapshot_drift":
      return "Existing campaign cases changed. Appended cases are supported; removed or replaced cases require a new campaign.";
    case "infeasible":
    default:
      return "Needs changes";
  }
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

// The single phrasing for an assignment count anywhere on the campaign screen: case level first,
// review-unit level in parentheses. Allocation is case-native (the planner assigns whole cases) but
// the durable rows are per review unit, so both numbers are real and neither alone is the answer.
// Previously the pre-publish panel quoted the case number and the publish result quoted the unit
// number with both labelled just "assignments", so one campaign read as 8 in one place and 40 in
// another. Every surface now says which is which, and says both.
export function assignmentCountsLabel(counts: AssignmentCounts): string {
  return `${plural(counts.cases, "case assignment")} (${plural(
    counts.review_units,
    "review-unit assignment",
  )})`;
}

// Plain-language summary for a publish result. The initial (non-incremental) publish has no
// "moved"/"revoked" concept, so it keeps the original single-count phrasing; an incremental
// publish reports new/moved counts and, when a roster removal actually took effect, how many
// reviewer(s) lost access (names are listed separately in the caller) -- replacing the old
// always-generic "Published N assignments." copy that gave no signal when a swap moved 0 *new*
// rows but did revoke a removed reviewer's work.
export function publishSummaryMessage(
  result: AllocationPublishResponse | IncrementalPublishResponse,
): string {
  if (!("moved_assignment_count" in result)) {
    return `Published ${assignmentCountsLabel(result.published_assignment_counts)}.`;
  }
  let message =
    `Published assignment update: ${assignmentCountsLabel(result.new_assignment_counts)} new, ` +
    `${assignmentCountsLabel(result.moved_assignment_counts)} moved.`;
  if (result.revoked_reviewer_ids.length > 0) {
    message +=
      ` ${result.revoked_reviewer_ids.length} reviewer` +
      `${result.revoked_reviewer_ids.length === 1 ? "" : "s"} lost access.`;
  }
  return message;
}

// Same two numbers for a preview, so "Preview assignment plan" and the publish result that follows
// it are directly comparable rather than being quoted at different granularities.
export function previewCountsMessage(
  result: AllocationPreviewResponse | IncrementalPreviewResponse,
): string {
  if ("planned_assignment_counts" in result) {
    return `Plans ${assignmentCountsLabel(result.planned_assignment_counts)}.`;
  }
  return (
    `Plans ${assignmentCountsLabel(result.new_assignment_counts)} new, ` +
    `${assignmentCountsLabel(result.moved_assignment_counts)} moved.`
  );
}

export function formatActivity(value: string | null | undefined) {
  if (!value) {
    return "Never signed in";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Never signed in" : parsed.toLocaleDateString();
}

export function apiErrorCode(error: unknown): string | null {
  return error instanceof ApiError
    ? ((error.body as { code?: string } | null)?.code ?? null)
    : null;
}

export function apiErrorDetail(error: unknown): string | null {
  return error instanceof ApiError
    ? ((error.body as { detail?: string } | null)?.detail ?? null)
    : null;
}

export function apiErrorFieldPaths(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const errors = (error.body as { errors?: Array<{ path?: Array<string | number> }> } | null)
    ?.errors;
  return (errors ?? [])
    .map((item) => item.path?.filter((part) => part !== "body").join("."))
    .filter((path): path is string => Boolean(path));
}

// RFC7807 `code` values raised by createCampaign/loadInputCases
// (see src/review_platform/review/campaign_admin.py, campaign_real_import.py).
export function campaignActionErrorMessage(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "campaign_key_exists":
      return "A campaign with this key already exists. Choose a different key.";
    case "campaign_no_cases_available":
      return (
        apiErrorDetail(error) ??
        "No cases or fields are available for this selection, so the campaign was not created."
      );
    case "campaign_case_field_conflict":
      return "One or more selected cases/fields are already assigned to another active campaign. Narrow the scope or choose different cases.";
    case "real_import_unavailable":
      return "Loading cases from the database is not configured in this environment. Ask an administrator to configure the case dataset and import the demo.";
    case "campaign_not_editable":
      return "Closed campaigns cannot load more cases.";
    default:
      return "The campaign action could not be completed. Check the campaign key and name and try again.";
  }
}

// RFC7807 `code` values raised by inviteReviewerToRoster (see api/platform_admin.py). A delivery
// failure means the roster write itself rolled back -- the reviewer was never added -- so the
// copy must never suggest the invite partially succeeded.
export function reviewerInviteErrorMessage(error: unknown): string {
  if (apiErrorCode(error) === "invitation_email_delivery_failed") {
    return "The invitation email could not be delivered, so the reviewer was not added to the roster. Check the address and try again.";
  }
  return "Reviewer could not be added to the roster. Check the address and try again.";
}

// Success copy keyed on the backend-confirmed `invitation_email` outcome -- never claim an email
// was sent unless the response says so.
export function reviewerInviteSuccessMessage(
  invitationEmail: "sent" | "resent" | "not_sent_already_active" | undefined,
): string {
  switch (invitationEmail) {
    case "resent":
      return "Reviewer is already on the roster and still pending. A reminder invitation email was re-sent.";
    case "not_sent_already_active":
      return "Reviewer is already active, so no invitation email was sent. They can already sign in.";
    case "sent":
    default:
      return "Reviewer added to the roster and an invitation email was sent. Use the activation link to choose a password; pending reviewers are not eligible for allocation yet.";
  }
}
