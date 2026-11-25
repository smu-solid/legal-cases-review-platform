import type { ProposalDecision, ProposalWorkspace } from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import type { LocalAdjudicationDecision, Verdict } from "./adjudicationDecisionState";

export function mergeProposalWorkspace(
  base: AdjudicationCaseWorkspace | undefined,
  extra: ProposalWorkspace | undefined,
): AdjudicationCaseWorkspace | undefined {
  if (!base || !extra?.ready) return base;
  const field_groups = base.field_groups.map((group) => {
    const members = extra.items.filter((i) => i.group_id === group.group_id);
    const replaced = new Set(members.map((i) => i.extracted_adjudication_id));
    const items = group.items.filter((i) => !replaced.has(i.adjudication_id));
    for (const proposal of members) {
      const original = group.items.find(
        (i) => i.adjudication_id === proposal.extracted_adjudication_id,
      );
      items.push({
        adjudication_id: proposal.id,
        review_unit_id: proposal.id,
        item_id: proposal.id,
        item_label: `Reviewer-added ${group.group_id === "cited_cases" ? "cited case" : "statute reference"}`,
        item_kind: "Reviewer-added",
        review_kind: group.items[0]?.review_kind ?? "citation_link",
        extracted_value_display: "",
        required_reviews: extra.required_reviews,
        submitted_reviews: proposal.reviewer_count,
        evidence_window_ids: [],
        assessment_targets: [],
        evidence_windows: [],
        submissions: [],
        ...original,
        membership_version: original?.membership_version ?? 0,
        participation_status: proposal.state === "submitted" ? "submitted" : "pending",
        proposal_item: proposal,
        proposal_source: {
          snapshotId: extra.source_snapshot_id,
          version: extra.source_version,
          snapshotIds: extra.source_snapshot_ids,
        },
        document_unit_id: original?.review_unit_id ?? group.items[0]?.review_unit_id,
      });
    }
    return { ...group, items };
  });
  return {
    ...base,
    field_groups,
    mode: field_groups.some((g) => g.items.some((i) => i.participation_status === "pending"))
      ? "edit"
      : "read_only",
  };
}

export function hydrateProposalDecision(
  item: AdjudicationWorkspaceItem,
  source: string,
): LocalAdjudicationDecision {
  const proposal = item.proposal_item!;
  const decision = proposal.draft ?? proposal.decision;
  const verdict: Verdict | null = decision?.preferred_proposal_id
    ? `proposal:${decision.preferred_proposal_id}`
    : decision?.preferred_submission_id
      ? `preferred:${decision.preferred_submission_id}`
      : decision?.outcome && decision.outcome !== "reviewer_preferred"
        ? decision.outcome
        : null;
  return {
    verdict,
    correctedValue: decision?.corrected_value ?? "",
    comment: decision?.comment ?? "",
    proposalVersion: proposal.lock_version,
    proposalSource: item.proposal_source,
    correctedProvenanceSpans: (decision?.provenance ?? []).map((s) => ({
      evidence_window_id: item.review_unit_id,
      char_start: s.char_start,
      char_end: s.char_end,
      selected_text: source.slice(s.char_start, s.char_end),
    })),
    dirty: false,
    saved: Boolean(decision),
    submitted: proposal.state === "submitted",
  };
}

export function proposalDecisionBody(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
): ProposalDecision {
  const source = local.proposalSource ?? item.proposal_source!;
  const preferred = local.verdict?.startsWith("preferred:");
  const proposal = local.verdict?.startsWith("proposal:");
  return {
    outcome:
      preferred || proposal ? "reviewer_preferred" : (local.verdict as ProposalDecision["outcome"]),
    preferred_proposal_id: proposal ? local.verdict!.slice(9) : null,
    preferred_submission_id: preferred ? local.verdict!.slice(10) : null,
    corrected_value: local.correctedValue,
    comment: local.comment,
    provenance: local.correctedProvenanceSpans.map((s) => ({
      source_snapshot_id: source.snapshotId,
      source_version: source.version,
      char_start: s.char_start,
      char_end: s.char_end,
    })),
  };
}

export function proposalDecisionReady(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
) {
  if (!local.verdict || item.proposal_item?.state !== "pending") return false;
  const noteRequired =
    Boolean(local.correctedValue.trim()) ||
    ["all_wrong", "unsupported_or_not_locatable", "exceptional_skip"].includes(local.verdict);
  if (
    local.correctedValue.trim() &&
    ["unsupported_or_not_locatable", "exceptional_skip"].includes(local.verdict)
  )
    return false;
  if (noteRequired && !local.comment.trim()) return false;
  if (local.correctedValue.trim() && !local.correctedProvenanceSpans.length) return false;
  if (local.verdict.startsWith("proposal:"))
    return item.proposal_item.proposals.some((p) => p.id === local.verdict!.slice(9));
  if (local.verdict.startsWith("preferred:"))
    return item.submissions.some((p) => p.submission_id === local.verdict!.slice(10));
  return true;
}
