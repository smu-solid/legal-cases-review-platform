import { useEffect } from "react";
import { submitReviewerCase } from "../../../api/reviewer";
import { useAuthSession } from "../../../auth/authSession";
import { type PreviewRow } from "../SubmitPreviewModal";
import { describeMutationError, emptyAnswer } from "../reviewerAnswerState";
import { proposalReady } from "../reviewerProposals";
import { useReviewerAnswerWrites } from "./useReviewerAnswerWrites";
import { useReviewerCaseSession } from "./useReviewerCaseSession";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerCaseActions({
  items,
  answers,
  writeInFlightRef,
  setIsSavingAllDrafts,
  saveMutation,
  versionFor,
  updateAnswer,
  setNavError,
  navigate,
  setIsLeaving,
  leaveGuardRef,
  setIsSubmittingCase,
  setCaseSubmitError,
  submitFieldWithRetry,
  setShowSubmitPreview,
  tenantId,
  assignmentId,
  session,
  queryClient,
  currentCaseIndex,
  orderedCases,
  caseTaskHref,
  campaignQueueHref,
}: {
  items: ReturnType<typeof useReviewerWorkspaceSelection>["items"];
  answers: ReturnType<typeof useReviewerWorkspaceState>["answers"];
  writeInFlightRef: ReturnType<typeof useReviewerWorkspaceState>["writeInFlightRef"];
  setIsSavingAllDrafts: ReturnType<typeof useReviewerWorkspaceState>["setIsSavingAllDrafts"];
  saveMutation: ReturnType<typeof useReviewerAnswerWrites>["saveMutation"];
  versionFor: ReturnType<typeof useReviewerAnswerWrites>["versionFor"];
  updateAnswer: ReturnType<typeof useReviewerAnswerWrites>["updateAnswer"];
  setNavError: ReturnType<typeof useReviewerWorkspaceState>["setNavError"];
  navigate: ReturnType<typeof useReviewerWorkspaceState>["navigate"];
  setIsLeaving: ReturnType<typeof useReviewerWorkspaceState>["setIsLeaving"];
  leaveGuardRef: ReturnType<typeof useReviewerWorkspaceState>["leaveGuardRef"];
  setIsSubmittingCase: ReturnType<typeof useReviewerWorkspaceState>["setIsSubmittingCase"];
  setCaseSubmitError: ReturnType<typeof useReviewerWorkspaceState>["setCaseSubmitError"];
  submitFieldWithRetry: ReturnType<typeof useReviewerAnswerWrites>["submitFieldWithRetry"];
  setShowSubmitPreview: ReturnType<typeof useReviewerWorkspaceState>["setShowSubmitPreview"];
  tenantId: string;
  assignmentId: string;
  session: ReturnType<typeof useAuthSession>;
  queryClient: ReturnType<typeof useReviewerAnswerWrites>["queryClient"];
  currentCaseIndex: ReturnType<typeof useReviewerCaseSession>["currentCaseIndex"];
  orderedCases: ReturnType<typeof useReviewerCaseSession>["orderedCases"];
  caseTaskHref: ReturnType<typeof useReviewerCaseSession>["caseTaskHref"];
  campaignQueueHref: ReturnType<typeof useReviewerCaseSession>["campaignQueueHref"];
}) {
  const previewRows: PreviewRow[] = items.map((item) => {
    const answer = answers[item.review_unit_id] ?? emptyAnswer;
    const fieldReady = item.reviewer_proposal
      ? proposalReady(answer)
      : answer.value_correct !== null &&
        answer.provenance_correct !== null &&
        !(
          answer.value_correct === false &&
          !answer.corrected_value.trim() &&
          !answer.comment.trim()
        );
    const hasUnsavedDraft =
      !answer.saved &&
      !answer.submitted &&
      (Boolean(item.reviewer_proposal) ||
        answer.value_correct !== null ||
        answer.provenance_correct !== null ||
        answer.corrected_value.trim() !== "" ||
        answer.comment.trim() !== "");
    return {
      item,
      valueCorrect: answer.value_correct,
      provenanceCorrect: answer.provenance_correct,
      correctedValue: answer.corrected_value,
      comment: answer.comment,
      failureReason: answer.failure_reason,
      ready: fieldReady,
      alreadySubmitted: answer.submitted,
      hasUnsavedDraft,
    };
  });

  const hasUnsavedWork = previewRows.some((row) => row.hasUnsavedDraft);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (hasUnsavedWork) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [hasUnsavedWork]);

  // For reviewer convenience from the case-submit preview: save every field with unsaved local
  // changes as a draft, without submitting anything. Independent of confirmCaseSubmit below.
  async function saveAllDrafts() {
    if (writeInFlightRef.current) throw new Error("A save is already in progress.");
    writeInFlightRef.current = true;
    setIsSavingAllDrafts(true);
    try {
      for (const row of previewRows.filter((row) => row.hasUnsavedDraft)) {
        const answer = answers[row.item.review_unit_id];
        if (!answer) {
          continue;
        }
        await saveMutation.mutateAsync({ item: row.item, answer, version: versionFor(row.item) });
        updateAnswer(row.item, { ...answer, saved: true });
      }
    } finally {
      writeInFlightRef.current = false;
      setIsSavingAllDrafts(false);
    }
  }

  // Move to another case (or the campaign queue) without silently dropping in-progress edits: any
  // field with unsaved local changes is auto-saved as a draft first. If a save fails, we stay put
  // and surface a friendly message rather than losing the reviewer's input. Bounded (only unsaved
  // fields) and re-entrancy-guarded via the shared write lock.
  async function leaveTo(to: string) {
    if (writeInFlightRef.current) {
      return;
    }
    const unsaved = previewRows.filter((row) => row.hasUnsavedDraft);
    if (unsaved.length === 0) {
      setNavError(null);
      navigate(to);
      return;
    }
    writeInFlightRef.current = true;
    setIsLeaving(true);
    try {
      for (const row of unsaved) {
        const answer = answers[row.item.review_unit_id];
        if (!answer) {
          continue;
        }
        await saveMutation.mutateAsync({ item: row.item, answer, version: versionFor(row.item) });
        updateAnswer(row.item, { ...answer, saved: true });
      }
      setNavError(null);
      navigate(to);
    } catch {
      setNavError(
        "We couldn't save your latest changes, so you're still on this case. Check your connection and try again.",
      );
    } finally {
      writeInFlightRef.current = false;
      setIsLeaving(false);
    }
  }
  leaveGuardRef.current = leaveTo;

  async function confirmCaseSubmit() {
    if (writeInFlightRef.current) return;
    writeInFlightRef.current = true;
    setIsSubmittingCase(true);
    try {
      await performCaseSubmit();
    } finally {
      writeInFlightRef.current = false;
      setIsSubmittingCase(false);
    }
  }

  async function performCaseSubmit() {
    setCaseSubmitError(null);
    const pending = previewRows.filter((row) => !row.alreadySubmitted && row.ready);
    for (const row of pending) {
      const answer = answers[row.item.review_unit_id];
      if (!answer) {
        continue;
      }
      try {
        // Same stale-conflict auto-retry and already-submitted handling as the single-field submit,
        // so a version that moved between opening the preview and confirming is incorporated rather
        // than aborting the whole case submit with a banner.
        await submitFieldWithRetry(row.item, answer, versionFor(row.item), true);
      } catch (error) {
        const description = describeMutationError(error);
        setCaseSubmitError({
          itemLabel: row.item.item_label,
          message: description?.message ?? "The submit failed.",
          isStale: description?.isStale ?? false,
        });
        return;
      }
    }
    if (items.length === 0) {
      setShowSubmitPreview(false);
      return;
    }
    try {
      await submitReviewerCase(tenantId, assignmentId, session.csrfToken);
      void queryClient.invalidateQueries({ queryKey: ["reviewer-case-queue", tenantId] });
      void queryClient.invalidateQueries({ queryKey: ["reviewer-campaign-queue", tenantId] });
    } catch (error) {
      const description = describeMutationError(error);
      setCaseSubmitError({
        itemLabel: "this case",
        message: description?.message ?? "The case could not be submitted.",
        isStale: description?.isStale ?? false,
      });
      return;
    }
    // Success: move the reviewer forward automatically -- to the next assigned case in this
    // campaign if one exists, otherwise back to the campaign queue/case list -- instead of leaving
    // them to click Next manually. Only reached after submitReviewerCase has actually resolved.
    setShowSubmitPreview(false);
    const nextCase = currentCaseIndex >= 0 ? orderedCases[currentCaseIndex + 1] : undefined;
    if (nextCase) {
      navigate(caseTaskHref(nextCase.anchor_assignment_id), {
        state: { caseSubmitToast: "Case submitted. Opening next case…" },
      });
    } else {
      navigate(campaignQueueHref, {
        state: { caseSubmitToast: "Case submitted. Returning to campaign queue…" },
      });
    }
  }
  return { previewRows, hasUnsavedWork, saveAllDrafts, leaveTo, confirmCaseSubmit };
}
