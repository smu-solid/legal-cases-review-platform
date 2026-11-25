import type { FieldGroup } from "../../../api/types";
import { emptyAnswer } from "../reviewerAnswerState";
import { useReviewerWorkspaceQueries } from "../useReviewerWorkspaceQueries";
import { useReviewerAnswerWrites } from "./useReviewerAnswerWrites";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerAdditionActions({
  writeInFlightRef,
  bundle,
  setPreserveSourceForItem,
  openAdditionRef,
  answers,
  setActiveItemId,
  setActiveAddGroupId,
  additions,
  setAnswers,
  setPickingProvenance,
  activeItem,
  activeAnswer,
  versionFor,
  activeGroup,
  bundleQuery,
  setNavError,
}: {
  writeInFlightRef: ReturnType<typeof useReviewerWorkspaceState>["writeInFlightRef"];
  bundle: ReturnType<typeof useReviewerWorkspaceSelection>["bundle"];
  setPreserveSourceForItem: ReturnType<
    typeof useReviewerWorkspaceState
  >["setPreserveSourceForItem"];
  openAdditionRef: ReturnType<typeof useReviewerWorkspaceState>["openAdditionRef"];
  answers: ReturnType<typeof useReviewerWorkspaceState>["answers"];
  setActiveItemId: ReturnType<typeof useReviewerWorkspaceState>["setActiveItemId"];
  setActiveAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["setActiveAddGroupId"];
  additions: ReturnType<typeof useReviewerWorkspaceSelection>["additions"];
  setAnswers: ReturnType<typeof useReviewerWorkspaceState>["setAnswers"];
  setPickingProvenance: ReturnType<typeof useReviewerWorkspaceState>["setPickingProvenance"];
  activeItem: ReturnType<typeof useReviewerWorkspaceSelection>["activeItem"];
  activeAnswer: ReturnType<typeof useReviewerWorkspaceSelection>["activeAnswer"];
  versionFor: ReturnType<typeof useReviewerAnswerWrites>["versionFor"];
  activeGroup: ReturnType<typeof useReviewerWorkspaceSelection>["activeGroup"];
  bundleQuery: ReturnType<typeof useReviewerWorkspaceQueries>["bundleQuery"];
  setNavError: ReturnType<typeof useReviewerWorkspaceState>["setNavError"];
}) {
  function startAddition(group: FieldGroup, selection?: { charStart: number; charEnd: number }) {
    if (writeInFlightRef.current || bundle?.case_submitted) return;
    setPreserveSourceForItem(undefined);
    const open = openAdditionRef.current;
    if (!selection && open && open.group === group.group_id && !answers[open.id]?.saved) {
      setActiveItemId(open.id);
      setActiveAddGroupId(null);
      requestAnimationFrame(() =>
        document.querySelector<HTMLInputElement>(".added-item-fields input")?.focus(),
      );
      return;
    }
    const proposal = additions.start(group);
    openAdditionRef.current = { id: proposal.id, group: group.group_id };
    const text = selection
      ? bundle!.source_render.content.slice(selection.charStart, selection.charEnd)
      : "";
    setAnswers((current) => ({
      ...current,
      [proposal.id]: {
        ...emptyAnswer,
        saved: false,
        corrected_value: text,
        corrected_provenance_spans: selection
          ? [
              {
                evidence_window_id: proposal.id,
                source_snapshot_id: bundle!.source_render.source_snapshot_id,
                source_version: bundle!.proposal_source_version!,
                char_start: selection.charStart,
                char_end: selection.charEnd,
                selected_text: text,
              },
            ]
          : [],
      },
    }));
    setActiveItemId(proposal.id);
    setActiveAddGroupId(null);
    setPickingProvenance(false);
  }

  async function removeAddition() {
    if (
      !activeItem?.reviewer_proposal ||
      !activeAnswer ||
      activeAnswer.submitted ||
      writeInFlightRef.current
    )
      return;
    writeInFlightRef.current = true;
    try {
      await additions.persist(activeItem, activeAnswer, versionFor(activeItem), "removed");
      openAdditionRef.current = null;
      setAnswers((current) => {
        const next = { ...current };
        delete next[activeItem.review_unit_id];
        return next;
      });
      // Stay beside the removed row and keep the reading position, rather than selecting the
      // first field of the case. An emptied group remains open at its Add row.
      const siblings = activeGroup?.items ?? [];
      const index = siblings.findIndex((item) => item.review_unit_id === activeItem.review_unit_id);
      const nextItem = siblings[index + 1] ?? siblings[index - 1];
      setPreserveSourceForItem(nextItem?.review_unit_id ?? null);
      setActiveItemId(nextItem?.review_unit_id ?? null);
      setActiveAddGroupId(nextItem ? null : (activeGroup?.group_id ?? null));
      setPickingProvenance(false);
      void bundleQuery.refetch();
    } catch {
      setNavError(
        "The addition could not be removed. Your draft is still here; refresh and retry.",
      );
    } finally {
      writeInFlightRef.current = false;
    }
  }
  return { startAddition, removeAddition };
}
