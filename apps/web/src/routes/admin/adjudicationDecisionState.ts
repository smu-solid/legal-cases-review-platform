import type {
  AdjudicationDecisionInput,
  AdjudicationDraftInput,
  AdjudicationWorkspaceItem,
  CorrectedProvenanceSpan,
} from "../../api/types";
import { hydrateProposalDecision, proposalDecisionReady } from "./adjudicationProposals";

export type FixedVerdict =
  "all_equivalent_supported" | "all_wrong" | "unsupported_or_not_locatable" | "exceptional_skip";
export type Verdict = `preferred:${string}` | `proposal:${string}` | FixedVerdict;
export type LocalAdjudicationSpan = CorrectedProvenanceSpan & { selected_text?: string };

export interface LocalAdjudicationDecision {
  verdict: Verdict | null;
  proposalVersion?: number;
  membershipVersion?: number;
  proposalSource?: { snapshotId: string; version: string };
  correctedValue: string;
  comment: string;
  correctedProvenanceSpans: LocalAdjudicationSpan[];
  saved: boolean;
  submitted: boolean;
  dirty: boolean;
}

export function formatAdjudicationCaseTitle(header: {
  neutral_citation_display?: string | null;
  case_title: string;
  reported_citation_display?: string | null;
}) {
  return [header.neutral_citation_display, header.case_title, header.reported_citation_display]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(" · ");
}

function verdictFor(
  decision: { outcome?: string | null; preferred_submission_id?: string | null } | null | undefined,
): Verdict | null {
  if (decision?.outcome === "reviewer_preferred" && decision.preferred_submission_id) {
    return `preferred:${decision.preferred_submission_id}`;
  }
  if (
    decision?.outcome &&
    [
      "all_equivalent_supported",
      "all_wrong",
      "unsupported_or_not_locatable",
      "exceptional_skip",
    ].includes(decision.outcome)
  ) {
    return decision.outcome as FixedVerdict;
  }
  return null;
}

export function hydrateAdjudicationDecision(item: AdjudicationWorkspaceItem, source: string) {
  if (item.proposal_item) return hydrateProposalDecision(item, source);
  const decision = item.draft?.decision ?? item.submitted_decision;
  return {
    verdict: verdictFor(decision),
    membershipVersion: item.membership_version ?? 0,
    correctedValue:
      decision?.corrected_value_display ??
      (typeof decision?.corrected_value === "string" ? decision.corrected_value : ""),
    comment: decision?.comment ?? "",
    correctedProvenanceSpans: (decision?.corrected_provenance_spans ?? []).map((span) => ({
      ...span,
      selected_text: source.slice(span.char_start, span.char_end),
    })),
    saved: Boolean(item.draft || item.submitted_decision),
    submitted: item.participation_status === "submitted",
    dirty: false,
  } satisfies LocalAdjudicationDecision;
}

export function buildAdjudicationDecision(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
): AdjudicationDecisionInput {
  const draft = buildAdjudicationDraft(item, local);
  if (!draft.outcome) throw new Error("A final adjudication decision is required.");
  return { ...draft, outcome: draft.outcome };
}

export function buildAdjudicationDraft(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
): AdjudicationDraftInput {
  const preferred = local.verdict?.startsWith("preferred:") ? local.verdict.slice(10) : null;
  const assessment = (submissionId: string) => {
    if (local.verdict === "all_equivalent_supported") return "correct" as const;
    if (local.verdict === "all_wrong") return "incorrect" as const;
    if (local.verdict === "unsupported_or_not_locatable" || local.verdict === "exceptional_skip")
      return "not_assessable" as const;
    return local.verdict === `preferred:${submissionId}`
      ? ("correct" as const)
      : ("incorrect" as const);
  };
  return {
    membership_version: local.membershipVersion ?? item.membership_version ?? 0,
    outcome: preferred ? "reviewer_preferred" : (local.verdict as FixedVerdict | null),
    preferred_submission_id: preferred,
    corrected_value: local.correctedValue || null,
    corrected_value_display: local.correctedValue || null,
    comment: local.comment || null,
    evidence_ids: item.evidence_window_ids,
    corrected_provenance_spans: local.correctedProvenanceSpans.map(
      ({ evidence_window_id, char_start, char_end, note }) => ({
        evidence_window_id,
        char_start,
        char_end,
        note: note ?? null,
      }),
    ),
    assessments: [],
    reviewer_assessments: local.verdict
      ? item.submissions.map((submission) => ({
          submission_id: submission.submission_id,
          assessment: assessment(submission.submission_id),
        }))
      : [],
  };
}

export function adjudicationDraftReady(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
) {
  return Boolean(local.verdict || (!item.proposal_item && local.dirty));
}

export function adjudicationDecisionReady(
  item: AdjudicationWorkspaceItem,
  local: LocalAdjudicationDecision,
) {
  if (item.proposal_item) return proposalDecisionReady(item, local);
  const requiresComment =
    local.verdict !== null &&
    ["all_wrong", "unsupported_or_not_locatable", "exceptional_skip"].includes(local.verdict);
  return (
    item.submissions.length >= item.required_reviews &&
    Boolean(local.verdict) &&
    (!requiresComment || Boolean(local.comment.trim()))
  );
}

export function verdictOptions(item: AdjudicationWorkspaceItem) {
  return [
    ...(item.proposal_item?.proposals ?? []).map((p) => ({
      value: `proposal:${p.id}` as Verdict,
      label: `${p.reviewer_label} · Proposal ${p.proposal_number} preferred: ${p.value}`,
    })),
    ...item.submissions.map((submission) => ({
      value: `preferred:${submission.submission_id}` as Verdict,
      label: `${submission.reviewer?.display_name || submission.reviewer?.email || submission.pseudonym} preferred`,
    })),
    { value: "all_equivalent_supported" as const, label: "All equivalent / supported" },
    { value: "all_wrong" as const, label: "All wrong" },
    { value: "unsupported_or_not_locatable" as const, label: "Unsupported / not locatable" },
    { value: "exceptional_skip" as const, label: "Skip (exceptional)" },
  ].slice(0, 9);
}
