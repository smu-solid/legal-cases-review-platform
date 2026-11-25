import { ApiError } from "../../api/client";
import type {
  CorrectedProvenanceSpan,
  ReviewItemAnswerInput,
  ReviewerGroupingBundle,
} from "../../api/types";
export type BooleanAnswer = boolean | null;

// A corrected-provenance span carries the exact selected source text alongside the char range,
// purely for reviewer-facing display (see the "Your marked provenance" box) -- `selected_text` is
// client-only and stripped before the answer reaches the API in buildAnswerPayload, since
// CorrectedProvenanceSpan is a `extra="forbid"` backend schema that would 422 on an unknown field.
export type LocalProvenanceSpan = CorrectedProvenanceSpan & {
  selected_text?: string;
  source_snapshot_id?: string | null;
  source_version?: string | null;
};

export interface LocalAnswer {
  duplicate_acknowledgement?: { fingerprint: string; reason: string } | null;
  value_correct: BooleanAnswer;
  provenance_correct: BooleanAnswer;
  corrected_value: string;
  comment: string;
  failure_reason: string;
  evidence_ids: string[];
  corrected_provenance_spans: LocalProvenanceSpan[];
  saved: boolean;
  submitted: boolean;
}

export const emptyAnswer: LocalAnswer = {
  value_correct: null,
  provenance_correct: null,
  corrected_value: "",
  comment: "",
  failure_reason: "",
  evidence_ids: [],
  corrected_provenance_spans: [],
  saved: false,
  submitted: false,
};

// Hydrates each item's local answer state from the server-persisted answer_summary/status, not
// just a blank slate -- otherwise a page reload (a fresh mount with no prior in-memory state) would
// visibly reset every previously-submitted field's green dot, corrected value, comment, reason, and
// marked provenance back to "not started" even though the backend already recorded them.
export function createInitialAnswers(bundle: ReviewerGroupingBundle) {
  const sourceContent = bundle.source_render.content;
  return Object.fromEntries(
    bundle.field_groups.flatMap((group) =>
      group.items.map((item) => {
        const summary = item.answer_summary;
        // Reconstruct the selected-text snippet for any server-persisted span too (not just spans
        // picked in the current session), so a reload still shows the quoted text, not only offsets.
        const spans: LocalProvenanceSpan[] = (summary?.corrected_provenance_spans ?? []).map(
          (span) => ({
            ...span,
            selected_text: sourceContent.slice(span.char_start, span.char_end),
          }),
        );
        // Items with no extracted value can never be marked "correct" -- neither the value nor its
        // provenance, since nothing was extracted to affirm. The backend hard-enforces this (422
        // missing_value_cannot_be_correct), so the reviewer is locked into "No" for BOTH controls
        // from the start rather than being allowed to pick "Yes" and get rejected on save; they must
        // supply the correct value and mark its provenance.
        const isMissing = item.extraction_state === "missing";
        const answer: LocalAnswer = {
          duplicate_acknowledgement: item.reviewer_proposal?.duplicate_acknowledgement,
          ...emptyAnswer,
          evidence_ids: item.evidence_window_ids,
          value_correct: isMissing ? false : (summary?.value_correct ?? null),
          provenance_correct: isMissing ? false : (summary?.provenance_correct ?? null),
          corrected_value: summary?.corrected_value_display ?? "",
          comment: summary?.comment ?? "",
          failure_reason: summary?.failure_reason ?? "",
          corrected_provenance_spans: spans,
          saved: item.status !== "not_started",
          submitted: item.status === "submitted",
        };
        return [item.review_unit_id, answer];
      }),
    ),
  ) as Record<string, LocalAnswer>;
}

// Exported solely for the regression test that pins the unsaved-edit merge invariant.
export function mergeHydratedAnswers(
  bundle: ReviewerGroupingBundle,
  current: Record<string, LocalAnswer>,
): Record<string, LocalAnswer> {
  // Server hydration fills missing items, while current in-memory values win for fields the
  // reviewer has already touched. This order is deliberate: a same-assignment background/refetch
  // must never overwrite unsaved edits.
  return { ...createInitialAnswers(bundle), ...current };
}

export function buildAnswerPayload(answer: LocalAnswer): ReviewItemAnswerInput {
  return {
    value_correct: answer.value_correct,
    provenance_correct: answer.provenance_correct,
    corrected_value: answer.corrected_value || null,
    corrected_value_display: answer.corrected_value || null,
    comment: answer.comment || null,
    failure_reason: answer.failure_reason || null,
    evidence_ids: answer.evidence_ids,
    // `selected_text` is client-only display state and must never reach the API -- the backend
    // schema forbids unknown fields.
    corrected_provenance_spans: answer.corrected_provenance_spans.map(
      ({ evidence_window_id, char_start, char_end, note, source_snapshot_id, source_version }) => ({
        ...(source_snapshot_id && source_version ? { source_snapshot_id, source_version } : {}),
        evidence_window_id,
        char_start,
        char_end,
        note: note ?? null,
      }),
    ),
  };
}

export interface MutationErrorDescription {
  message: string;
  isStale: boolean;
}

// The stable problem-detail `code` (see common/errors.py) is the only reliable signal for *why* a
// mutation failed; the HTTP status alone is ambiguous (409 covers both "already submitted" and
// "lease expired").
export function errorCode(error: unknown): string | null {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    const code = (error.body as { code?: unknown }).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

// The reviewer already submitted this field (a double-fire, or a resubmit of a done field). The
// backend rejects the second write with 409 `assignment_not_editable`; the workspace treats it as a
// success (the field is done) rather than a conflict, so it never reaches the error banner.
// A field moved to another reviewer answers with its own `released_assignment` code precisely so it
// does NOT land here: reading it as "already submitted" marked fields the reviewer had never
// answered as done, and hid the reason the case would not submit.
export function isAlreadySubmittedError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    errorCode(error) === "assignment_not_editable"
  );
}

// A true stale-write conflict — the field's version moved after the reviewer loaded it (412
// precondition-failed), or its lease lapsed (409 lease-expired) — must read differently from an
// ordinary failure: the fix is "refresh and review again," not "retry the same data." The
// already-submitted 409 is handled upstream as a success and deliberately excluded here.
// A lease-expired 409 gets its own honest copy: the backend self-heals a lapsed lease whenever
// the field's slot is still free, so one reaching the client means other reviewers have since
// filled the unit's capacity — "review once more before submitting" would be a false promise.
export function describeMutationError(error: unknown): MutationErrorDescription | null {
  if (!error || isAlreadySubmittedError(error)) {
    return null;
  }
  const code = errorCode(error);
  const isStale =
    error instanceof ApiError &&
    (error.status === 412 || (error.status === 409 && code !== "assignment_not_editable"));
  const byCode: Record<string, string> = {
    proposal_incomplete: "Enter a value and mark supporting provenance before submitting.",
    proposal_provenance_invalid:
      "The marked provenance does not match the current source. Clear it and mark supporting text again.",
    proposal_group_ineligible:
      "This group is no longer available for additions in your assignment. Refresh the workspace.",
    proposal_locked: "This addition is read-only.",
    case_submitted: "Your submitted case is read-only.",
    released_assignment:
      "This field was reassigned to another reviewer, so it is no longer yours to answer. Refresh to see the work you currently hold.",
    case_not_fully_submitted:
      "Some fields of this case are still unanswered. Submit every field shown above, then submit the case.",
    assignment_lease_expired:
      "Your hold on this field expired and its review slots have since been filled by other reviewers. Refresh to see the latest state.",
  };
  const staleMessage =
    "This field was updated after you loaded it. We refreshed the latest state — please review once more before submitting.";
  return {
    isStale,
    message:
      (code ? byCode[code] : undefined) ??
      (isStale
        ? staleMessage
        : error instanceof ApiError &&
            error.body &&
            typeof error.body === "object" &&
            "detail" in error.body &&
            typeof error.body.detail === "string"
          ? error.body.detail
          : "The save failed. Check your connection and try again."),
  };
}

type ItemStatusKind = "submitted" | "draft" | "in_progress" | "not_started";

export function itemStatus(answer: LocalAnswer | undefined): {
  label: string;
  kind: ItemStatusKind;
} {
  if (!answer) {
    return { label: "Not started", kind: "not_started" };
  }

  if (answer.submitted) {
    return { label: "Submitted", kind: "submitted" };
  }

  if (answer.saved) {
    return { label: "Draft saved", kind: "draft" };
  }

  if (
    answer.value_correct !== null ||
    answer.provenance_correct !== null ||
    answer.corrected_value.trim() ||
    answer.corrected_provenance_spans.length
  ) {
    return { label: "In progress", kind: "in_progress" };
  }

  return { label: "Not started", kind: "not_started" };
}
