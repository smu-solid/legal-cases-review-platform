import { apiRequest } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import type { FieldGroup, GroupItem, ReviewerGroupingBundle } from "../../api/types";
import type { LocalAnswer } from "./reviewerAnswerState";

export type ReviewerProposal = components["schemas"]["ReviewerProposal"];
export type ProposalSpan = components["schemas"]["ProposalSpan"];
export type ProposalInput = components["schemas"]["ProposalInput"];

export function proposalItem(proposal: ReviewerProposal, assignmentId: string): GroupItem {
  return {
    reviewer_proposal: proposal,
    extraction_state: "present",
    cross_source_disagreement: false,
    review_unit_id: proposal.id,
    assignment_id: assignmentId,
    item_id: proposal.id,
    item_kind: "reviewer_added",
    item_label:
      "Reviewer-added " +
      (proposal.group_id === "cited_cases" ? "cited case" : "statute reference"),
    extracted_value_display: proposal.value || "New item (incomplete)",
    evidence_window_ids: [],
    status: proposal.state === "submitted" ? "submitted" : "draft",
    lock_version: proposal.lock_version,
    answer_summary: {
      state: proposal.state === "submitted" ? "submitted" : "draft",
      value_correct: null,
      provenance_correct: null,
      corrected_value_display: proposal.value,
      comment: proposal.note,
      corrected_provenance_spans: (proposal.provenance ?? []).map((span) => ({
        ...span,
        evidence_window_id: proposal.id,
      })),
    },
  };
}

export function projectProposals(
  bundle: ReviewerGroupingBundle,
  proposals: ReviewerProposal[],
  assignmentId: string,
): ReviewerGroupingBundle {
  return {
    ...bundle,
    field_groups: bundle.field_groups.map((group) => {
      const items = [
        ...group.items,
        ...proposals
          .filter((p) => p.group_id === group.group_id && p.state !== "removed")
          .map((p) => proposalItem(p, assignmentId)),
      ];
      return {
        ...group,
        items,
        item_count: items.length,
        completed_count: items.filter((item) => item.status === "submitted").length,
      };
    }),
  };
}

export function proposalReady(answer: LocalAnswer): boolean {
  return Boolean(answer.corrected_value.trim() && answer.corrected_provenance_spans.length);
}

export function proposalInput(item: GroupItem, answer: LocalAnswer): ProposalInput {
  return {
    duplicate_acknowledgement: answer.duplicate_acknowledgement?.reason.trim()
      ? answer.duplicate_acknowledgement
      : null,
    group_id: item.reviewer_proposal!.group_id,
    value: answer.corrected_value,
    note: answer.comment,
    provenance: answer.corrected_provenance_spans.map((span) => ({
      source_snapshot_id: span.source_snapshot_id!,
      source_version: span.source_version!,
      char_start: span.char_start,
      char_end: span.char_end,
    })),
  };
}

export function persistProposal(
  tenantId: string,
  item: GroupItem,
  answer: LocalAnswer,
  version: number,
  state: "draft" | "submitted" | "removed",
  csrfToken: string | null,
  key: string,
) {
  return apiRequest<ReviewerProposal>(
    `/tenants/${tenantId}/review/assignments/${item.assignment_id}/proposals/${item.review_unit_id}/${state}`,
    {
      method: "PUT",
      body: proposalInput(item, answer),
      ifMatch: version,
      csrfToken,
      idempotencyKey: key,
    },
  );
}

export function newProposal(group: FieldGroup): ReviewerProposal {
  return {
    id: crypto.randomUUID(),
    group_id: group.group_id,
    value: "",
    original_value: "",
    note: "",
    provenance: [],
    state: "draft",
    lock_version: 1,
    created_at: new Date().toISOString(),
    value_schema:
      group.group_id === "cited_cases" ? "cited_case_text/v1" : "statute_reference_text/v1",
  };
}
