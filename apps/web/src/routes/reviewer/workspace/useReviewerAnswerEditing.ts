import { type LocalProvenanceSpan } from "../reviewerAnswerState";
import { useReviewerAnswerWrites } from "./useReviewerAnswerWrites";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerAnswerEditing({
  bundle,
  activeGroup,
  activeAddGroupId,
  selectItem,
  activeItem,
  activeAnswer,
  updateAnswer,
  setPickingProvenance,
}: {
  bundle: ReturnType<typeof useReviewerWorkspaceSelection>["bundle"];
  activeGroup: ReturnType<typeof useReviewerWorkspaceSelection>["activeGroup"];
  activeAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["activeAddGroupId"];
  selectItem: ReturnType<typeof useReviewerAnswerWrites>["selectItem"];
  activeItem: ReturnType<typeof useReviewerWorkspaceSelection>["activeItem"];
  activeAnswer: ReturnType<typeof useReviewerWorkspaceSelection>["activeAnswer"];
  updateAnswer: ReturnType<typeof useReviewerAnswerWrites>["updateAnswer"];
  setPickingProvenance: ReturnType<typeof useReviewerWorkspaceState>["setPickingProvenance"];
}) {
  function jumpToNextGroup() {
    if (!bundle || !activeGroup) {
      return;
    }
    const groupIndex = bundle.field_groups.findIndex(
      (g) => g.group_id === (activeAddGroupId ?? activeGroup.group_id),
    );
    const nextGroup = bundle.field_groups[(groupIndex + 1) % bundle.field_groups.length];
    const firstItem = nextGroup?.items[0];
    if (firstItem) {
      selectItem(firstItem);
    }
  }

  function setValueAnswer(value: boolean) {
    if (!activeItem || !activeAnswer || activeAnswer.submitted || bundle?.case_submitted) {
      return;
    }
    updateAnswer(activeItem, {
      ...activeAnswer,
      saved: false,
      submitted: false,
      value_correct: value,
      failure_reason: activeAnswer.failure_reason,
      provenance_correct: value === false ? false : activeAnswer.provenance_correct,
    });
  }

  function setProvenanceAnswer(value: boolean) {
    if (!activeItem || !activeAnswer || activeAnswer.submitted || bundle?.case_submitted) {
      return;
    }
    // Answering YES withdraws the correction: any span marked while the answer was NO is dropped,
    // and marking mode cannot stay open behind the now-hidden control.
    if (value) {
      setPickingProvenance(false);
    }
    updateAnswer(activeItem, {
      ...activeAnswer,
      saved: false,
      submitted: false,
      provenance_correct: value,
      failure_reason: activeAnswer.failure_reason,
      corrected_provenance_spans: value ? [] : activeAnswer.corrected_provenance_spans,
    });
  }

  function handleProvenancePick(charStart: number, charEnd: number) {
    if (!bundle || !activeItem || !activeAnswer) {
      return;
    }
    if (
      activeAnswer.submitted ||
      (!activeItem.reviewer_proposal && activeAnswer.provenance_correct !== false)
    ) {
      return;
    }
    const evidenceWindowId = activeItem.reviewer_proposal
      ? activeItem.review_unit_id
      : activeItem.evidence_window_ids[0];
    if (!evidenceWindowId) {
      return;
    }
    const span: LocalProvenanceSpan = {
      evidence_window_id: evidenceWindowId,
      ...(activeItem.reviewer_proposal || activeGroup?.group_id === "cited_cases"
        ? {
            source_snapshot_id: bundle.source_render.source_snapshot_id,
            source_version: bundle.proposal_source_version!,
          }
        : {}),
      char_start: charStart,
      char_end: charEnd,
      selected_text: bundle.source_render.content.slice(charStart, charEnd),
    };
    updateAnswer(activeItem, {
      ...activeAnswer,
      saved: false,
      submitted: false,
      corrected_provenance_spans: [
        ...activeAnswer.corrected_provenance_spans.filter(
          (old) => old.char_start !== charStart || old.char_end !== charEnd,
        ),
        span,
      ],
    });
    setPickingProvenance(false);
  }
  return { jumpToNextGroup, setValueAnswer, setProvenanceAnswer, handleProvenancePick };
}
