import type { AppliedCaseSelectionState } from "./CampaignCaseSelectionPanel";
import { apiErrorCode, apiErrorDetail, apiErrorFieldPaths } from "./adminFormatters";

export function caseFilterSummary(
  filter: AppliedCaseSelectionState["caseFilter"] | null | undefined,
): string {
  const values = (filter?.all ?? []).map((clause) => {
    if (clause.field_id === "case_subject") return `Case subject: ${String(clause.value)}`;
    const ranges =
      typeof clause.value === "object" && clause.value && "ranges" in clause.value
        ? (clause.value.ranges as Array<{ start: number; end: number }>)
        : [];
    const years = ranges
      .map(({ start, end }) => (start === end ? String(start) : `${start}-${end}`))
      .join(", ");
    return `Judgment year: ${years}`;
  });
  return values.length > 0 ? values.join("; ") : "No filter applied";
}

export function editErrorMessage(error: unknown): string {
  if (apiErrorCode(error) === "validation_failed") {
    const paths = apiErrorFieldPaths(error);
    return paths.length > 0
      ? `The campaign could not be updated because these fields are invalid: ${paths.join(", ")}.`
      : (apiErrorDetail(error) ?? "The campaign request is invalid.");
  }
  switch (apiErrorCode(error)) {
    case "campaign_not_editable":
      return "Closed campaigns cannot be edited.";
    case "campaign_edit_requires_confirmation":
      return "confirmation_required";
    case "campaign_scope_conflict":
      // Names the campaigns already holding the fields, so the admin can act on it.
      return (
        apiErrorDetail(error) ??
        "Another campaign already holds these fields for cases in this campaign."
      );
    default:
      return apiErrorDetail(error) ?? "The campaign could not be updated.";
  }
}

export function deleteErrorMessage(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "campaign_delete_work_exists":
      return "This campaign has saved, submitted, or revision-requested reviewer work and cannot be deleted. Close or supersede it instead.";
    case "campaign_delete_pool_blocked":
      return "The shared case pool is not a campaign and cannot be deleted.";
    case "campaign_delete_invalid_status":
      return apiErrorDetail(error) ?? "This campaign's current status does not allow deletion.";
    case "campaign_delete_requires_confirmation":
      return "confirmation_required";
    default:
      return `The campaign could not be deleted${
        apiErrorDetail(error)
          ? `: ${apiErrorDetail(error)}`
          : ". Try again, or contact support if the problem persists."
      }`;
  }
}

export function loadCasesErrorMessage(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "campaign_not_editable":
      return "Closed campaigns cannot load more cases.";
    case "campaign_no_cases_available":
      return apiErrorDetail(error) ?? "No cases or fields remain for this campaign scope.";
    default:
      return "Cases could not be loaded from the pool. Try again, or adjust the requested count.";
  }
}

export function completeErrorMessage(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "campaign_not_completable":
      return "Only a published campaign can be marked completed.";
    default:
      return "The campaign could not be marked completed.";
  }
}

export function reviewerActionErrorMessage(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "campaign_reviewers_locked":
      return "Reviewers cannot be changed after the campaign is closed.";
    case "campaign_reviewer_work_exists":
      return "This reviewer has already saved or submitted work in this campaign and cannot be removed.";
    case "campaign_reviewer_minimum_required":
      return "A campaign with published assignments must keep at least one selected reviewer.";
    case "reviewer_not_eligible":
      return "That reviewer is not an active, eligible member of this tenant.";
    case "too_many_selected_reviewers":
      return "This campaign already has the maximum number of selected reviewers.";
    default:
      return "The reviewer could not be updated.";
  }
}
