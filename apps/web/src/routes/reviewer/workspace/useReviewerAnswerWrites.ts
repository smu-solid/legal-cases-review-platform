import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { saveAnswerDraft, submitAnswer } from "../../../api/reviewer";
import type { GroupItem } from "../../../api/types";
import { useAuthSession } from "../../../auth/authSession";
import {
  buildAnswerPayload,
  describeMutationError,
  isAlreadySubmittedError,
  type LocalAnswer,
} from "../reviewerAnswerState";
import { allItems } from "../reviewerWorkspaceSelectors";
import { useReviewerWorkspaceQueries } from "../useReviewerWorkspaceQueries";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerAnswerWrites({
  additions,
  duplicateFeedback,
  tenantId,
  session,
  setLockVersions,
  assignmentId,
  lockVersions,
  setPickingProvenance,
  activeItemId,
  bundleQuery,
  setAnswers,
  items,
  answers,
  activeItem,
  activeAnswer,
  bundle,
  writeInFlightRef,
  setShowSubmitPreview,
  setPreserveSourceForItem,
  setActiveAddGroupId,
  setActiveItemId,
  activeAddGroupId,
}: {
  additions: ReturnType<typeof useReviewerWorkspaceSelection>["additions"];
  duplicateFeedback: ReturnType<typeof useReviewerWorkspaceSelection>["duplicateFeedback"];
  tenantId: string;
  session: ReturnType<typeof useAuthSession>;
  setLockVersions: ReturnType<typeof useReviewerWorkspaceState>["setLockVersions"];
  assignmentId: string;
  lockVersions: ReturnType<typeof useReviewerWorkspaceState>["lockVersions"];
  setPickingProvenance: ReturnType<typeof useReviewerWorkspaceState>["setPickingProvenance"];
  activeItemId: ReturnType<typeof useReviewerWorkspaceState>["activeItemId"];
  bundleQuery: ReturnType<typeof useReviewerWorkspaceQueries>["bundleQuery"];
  setAnswers: ReturnType<typeof useReviewerWorkspaceState>["setAnswers"];
  items: ReturnType<typeof useReviewerWorkspaceSelection>["items"];
  answers: ReturnType<typeof useReviewerWorkspaceState>["answers"];
  activeItem: ReturnType<typeof useReviewerWorkspaceSelection>["activeItem"];
  activeAnswer: ReturnType<typeof useReviewerWorkspaceSelection>["activeAnswer"];
  bundle: ReturnType<typeof useReviewerWorkspaceSelection>["bundle"];
  writeInFlightRef: ReturnType<typeof useReviewerWorkspaceState>["writeInFlightRef"];
  setShowSubmitPreview: ReturnType<typeof useReviewerWorkspaceState>["setShowSubmitPreview"];
  setPreserveSourceForItem: ReturnType<
    typeof useReviewerWorkspaceState
  >["setPreserveSourceForItem"];
  setActiveAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["setActiveAddGroupId"];
  setActiveItemId: ReturnType<typeof useReviewerWorkspaceState>["setActiveItemId"];
  activeAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["activeAddGroupId"];
}) {
  const queryClient = useQueryClient();

  // Submitting (and, for the bundle's own lock_version, saving) changes assignment/campaign
  // progress that the reviewer's own queue and the admin monitor both surface -- invalidate both
  // so neither shows stale counts after this session's mutation. `reviewer-grouped-bundle` is
  // scoped to this assignment only, so a stale `lock_version` never leaks across assignments.
  type MutationVars = { item: GroupItem; answer: LocalAnswer; version: number };

  const saveMutation = useMutation({
    mutationFn: async ({
      item,
      answer,
      version,
    }: MutationVars): Promise<{ lock_version: number }> => {
      if (item.reviewer_proposal) {
        const result = await additions.persist(item, answer, version, "draft");
        await duplicateFeedback.check(item, answer);
        return result;
      }
      return saveAnswerDraft(
        tenantId,
        item.assignment_id,
        version,
        buildAnswerPayload(answer),
        session.csrfToken,
      );
    },
    onSuccess: (result, { item }) => {
      setLockVersions((current) => ({ ...current, [item.review_unit_id]: result.lock_version }));
      void queryClient.invalidateQueries({
        queryKey: ["reviewer-grouped-bundle", tenantId, assignmentId],
      });
    },
  });

  const submitMutation = useMutation({
    mutationFn: async ({
      item,
      answer,
      version,
    }: MutationVars): Promise<{ lock_version: number }> => {
      if (item.reviewer_proposal) {
        await duplicateFeedback.check(item, answer);
        return additions.persist(item, answer, version, "submitted");
      }
      return submitAnswer(
        tenantId,
        item.assignment_id,
        version,
        buildAnswerPayload(answer),
        session.csrfToken,
      );
    },
    onSuccess: (result, { item }) => {
      setLockVersions((current) => ({ ...current, [item.review_unit_id]: result.lock_version }));
      void queryClient.invalidateQueries({
        queryKey: ["reviewer-grouped-bundle", tenantId, assignmentId],
      });
      void queryClient.invalidateQueries({ queryKey: ["reviewer-campaign-queue", tenantId] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue", tenantId] });
      void queryClient.invalidateQueries({ queryKey: ["admin-campaign-progress", tenantId] });
    },
  });

  // The If-Match version for the next write to a field: the freshest value returned by this
  // session's own save/submit, falling back to the bundle's version on first write.
  function versionFor(item: GroupItem) {
    return lockVersions[item.review_unit_id] ?? item.lock_version;
  }

  // Selecting a different field clears any stale-write banner from the previously active field --
  // it belongs to that field's mutation attempt, not the newly selected one.
  useEffect(() => {
    setPickingProvenance(false);
    saveMutation.reset();
    submitMutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeItemId]);

  function refreshAfterConflict() {
    saveMutation.reset();
    submitMutation.reset();
    // Discard this session's tracked versions so the refetched bundle's authoritative
    // lock_version is used for the next write.
    setLockVersions({});
    void bundleQuery.refetch();
  }

  function updateAnswer(item: GroupItem, nextAnswer: LocalAnswer) {
    setAnswers((current) => {
      const previous = current[item.review_unit_id];
      const changed =
        previous &&
        (previous.corrected_value !== nextAnswer.corrected_value ||
          JSON.stringify(previous.corrected_provenance_spans) !==
            JSON.stringify(nextAnswer.corrected_provenance_spans));
      const next = { ...current, [item.review_unit_id]: nextAnswer };
      if (changed)
        Object.keys(next).forEach((id) => {
          if (!next[id].submitted && next[id].duplicate_acknowledgement)
            next[id] = { ...next[id], duplicate_acknowledgement: null, saved: false };
        });
      return next;
    });
  }

  // After a field is submitted, move focus to the next field that still needs an answer (wrapping
  // to the top), so the reviewer advances through the case without hunting for the next open field.
  function advanceToNextUnsubmitted(submittedItemId: string) {
    const ordered = [
      ...items.slice(items.findIndex((it) => it.review_unit_id === submittedItemId) + 1),
      ...items.slice(0, items.findIndex((it) => it.review_unit_id === submittedItemId) + 1),
    ];
    const next = ordered.find(
      (it) => it.review_unit_id !== submittedItemId && !answers[it.review_unit_id]?.submitted,
    );
    if (next) {
      selectItem(next);
    }
  }

  async function saveCurrent() {
    if (!activeItem || !activeAnswer || activeAnswer.submitted || bundle?.case_submitted) {
      return;
    }
    // Ignore re-entrant saves/submits (double key-press, click during an in-flight request): a
    // second write with the now-consumed version would 409/412 for no reason.
    if (writeInFlightRef.current) {
      return;
    }

    const item = activeItem;
    const answer = activeAnswer;
    writeInFlightRef.current = true;
    try {
      await saveMutation.mutateAsync({ item, answer, version: versionFor(item) });
      setAnswers((current) =>
        current[item.review_unit_id] === answer
          ? { ...current, [item.review_unit_id]: { ...answer, saved: true } }
          : current,
      );
    } catch {
      // The mutation error remains visible in the field editor.
    } finally {
      writeInFlightRef.current = false;
    }
  }

  async function submitFieldWithRetry(
    item: GroupItem,
    answer: LocalAnswer,
    version: number,
    allowRetry: boolean,
  ): Promise<void> {
    try {
      await submitMutation.mutateAsync({ item, answer, version });
      updateAnswer(item, { ...answer, saved: true, submitted: true });
    } catch (error) {
      if (isAlreadySubmittedError(error)) {
        updateAnswer(item, { ...answer, saved: true, submitted: true });
        submitMutation.reset();
        return;
      }
      const description = describeMutationError(error);
      if (allowRetry && description?.isStale && !item.reviewer_proposal) {
        const refreshed = await bundleQuery.refetch();
        const fresh = allItems(refreshed.data).find(
          (it) => it.review_unit_id === item.review_unit_id,
        );
        if (fresh) {
          setLockVersions((current) => ({ ...current, [item.review_unit_id]: fresh.lock_version }));
          if (fresh.status === "submitted") {
            // Already submitted server-side; adopt that as success.
            updateAnswer(item, { ...answer, saved: true, submitted: true });
            submitMutation.reset();
            return;
          }
          // Clear the stale error just before a clean retry so no banner flashes.
          submitMutation.reset();
          await submitFieldWithRetry(item, answer, fresh.lock_version, false);
          return;
        }
      }
      // Unrecoverable: leave the error on submitMutation (inline banner) and let the caller react.
      throw error;
    }
  }

  async function submitCurrent() {
    if (!activeItem || !activeAnswer || activeAnswer.submitted || bundle?.case_submitted) {
      return;
    }
    if (activeItem.reviewer_proposal && duplicateFeedback.data?.conflicts?.length) {
      return;
    }
    if (writeInFlightRef.current) {
      return;
    }

    const item = activeItem;
    const answer = activeAnswer;
    // Capture this before the async write updates local state. The final outstanding field can be
    // anywhere in the ordered group list, so derive it from submitted status rather than position.
    const completesAllFields =
      !answer.submitted &&
      items.filter((candidate) => !answers[candidate.review_unit_id]?.submitted).length === 1;
    writeInFlightRef.current = true;
    try {
      await submitFieldWithRetry(item, answer, versionFor(item), true);
      if (completesAllFields) {
        setShowSubmitPreview(true);
      } else {
        advanceToNextUnsubmitted(item.review_unit_id);
      }
    } catch {
      // Failure is already reflected in submitMutation.error and renders through the AnswerPanel
      // banner via describeMutationError; nothing else to do here.
    } finally {
      writeInFlightRef.current = false;
    }
  }

  async function openAssociatedItem(id: string) {
    const target = items.find((item) => item.review_unit_id === id);
    if (!target || writeInFlightRef.current) return;
    if (activeItem && activeAnswer && !activeAnswer.saved && !activeAnswer.submitted) {
      writeInFlightRef.current = true;
      try {
        await saveMutation.mutateAsync({
          item: activeItem,
          answer: activeAnswer,
          version: versionFor(activeItem),
        });
        updateAnswer(activeItem, { ...activeAnswer, saved: true });
      } catch {
        return;
      } finally {
        writeInFlightRef.current = false;
      }
    }
    selectItem(target);
  }

  function selectItem(item: GroupItem) {
    setPreserveSourceForItem(undefined);
    setActiveAddGroupId(null);
    setActiveItemId(item.review_unit_id);
    setPickingProvenance(false);
  }

  function stepItem(direction: 1 | -1) {
    const stops =
      bundle?.field_groups.flatMap((group) => [
        ...group.items.map((item) => ({ id: item.review_unit_id, item: item as GroupItem, group })),
        ...(group.add_item_label ? [{ id: `add:${group.group_id}`, item: null, group }] : []),
      ]) ?? [];
    const current = activeAddGroupId ? `add:${activeAddGroupId}` : activeItemId;
    const index = stops.findIndex((stop) => stop.id === current);
    const next = stops[Math.max(0, Math.min(stops.length - 1, index + direction))];
    if (!next) return;
    if (next.item) {
      selectItem(next.item);
      document.querySelector<HTMLButtonElement>(`[data-review-item="${next.id}"]`)?.focus();
    } else {
      setActiveAddGroupId(next.group.group_id);
      document
        .querySelector<HTMLButtonElement>(`[data-add-group="${next.group.group_id}"]`)
        ?.focus();
    }
  }

  return {
    queryClient,
    saveMutation,
    submitMutation,
    versionFor,
    refreshAfterConflict,
    updateAnswer,
    saveCurrent,
    submitFieldWithRetry,
    submitCurrent,
    openAssociatedItem,
    selectItem,
    stepItem,
  };
}
