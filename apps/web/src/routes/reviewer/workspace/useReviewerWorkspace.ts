import { useRef, useState } from "react";
import { useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { useAuthSession } from "../../../auth/authSession";
import { type WorkspaceSourceView } from "../../../components/WorkspaceSourcePane";
import type { AppLayoutOutletContext } from "../../../layout/AppLayout";
import { type LocalAnswer, type MutationErrorDescription } from "../reviewerAnswerState";
import { proposalReady } from "../reviewerProposals";
import { useCaseSubmitToast } from "../useCaseSubmitToast";
import { useReviewerKeyboard } from "../useReviewerKeyboard";
import { useReviewerWorkspaceQueries } from "../useReviewerWorkspaceQueries";
import { useReviewerAdditionActions } from "./useReviewerAdditionActions";
import { useReviewerAnswerEditing } from "./useReviewerAnswerEditing";
import { useReviewerAnswerWrites } from "./useReviewerAnswerWrites";
import { useReviewerCaseActions } from "./useReviewerCaseActions";
import { useReviewerCaseSession } from "./useReviewerCaseSession";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerWorkspaceState(
  sourceView: WorkspaceSourceView,
  setSourceView: React.Dispatch<React.SetStateAction<WorkspaceSourceView>>,
) {
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [preserveSourceForItem, setPreserveSourceForItem] = useState<string | null>();
  const [answers, setAnswers] = useState<Record<string, LocalAnswer>>({});
  // The freshest optimistic-concurrency version per field, captured from each save/submit response.
  // A draft save bumps the assignment's server-side lock_version, so a subsequent submit must send
  // the *new* version as If-Match; relying on the bundle's `item.lock_version` alone would send a
  // stale version until an async refetch lands, producing a spurious 412 on Save draft -> Submit.
  const [lockVersions, setLockVersions] = useState<Record<string, number>>({});
  // Synchronous re-entrancy lock. React Query's `isPending` only flips on the next render, so two
  // Submit presses fired in the same tick (double-click, key-repeat) would both pass an isPending
  // check and hit the server twice — the second failing with a spurious 409. This ref blocks the
  // second call immediately, before any re-render.
  const writeInFlightRef = useRef(false);
  const openAdditionRef = useRef<{ id: string; group: string } | null>(null);
  const [pickingProvenance, setPickingProvenance] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showSubmitPreview, setShowSubmitPreview] = useState(false);
  const [isSubmittingCase, setIsSubmittingCase] = useState(false);
  const [isSavingAllDrafts, setIsSavingAllDrafts] = useState(false);
  const [caseSubmitError, setCaseSubmitError] = useState<
    (MutationErrorDescription & { itemLabel: string }) | null
  >(null);
  const navigate = useNavigate();
  // Brief success banner set via router navigation state by a prior confirmCaseSubmit auto-navigate
  // (this page for "opened next case", ReviewerQueuePage for "returned to campaign queue").
  const caseSubmitToast = useCaseSubmitToast();
  const [isLeaving, setIsLeaving] = useState(false);
  const [navError, setNavError] = useState<string | null>(null);
  // Holds the latest unsaved-guarded navigation handler so the footer slot (published once via an
  // effect, then not re-rendered on every keystroke) always calls the current closure over answers.
  const leaveGuardRef = useRef<(to: string) => void>(() => {});
  return {
    activeItemId,
    setActiveItemId,
    preserveSourceForItem,
    setPreserveSourceForItem,
    answers,
    setAnswers,
    lockVersions,
    setLockVersions,
    writeInFlightRef,
    openAdditionRef,
    sourceView,
    setSourceView,
    pickingProvenance,
    setPickingProvenance,
    showShortcuts,
    setShowShortcuts,
    showSubmitPreview,
    setShowSubmitPreview,
    isSubmittingCase,
    setIsSubmittingCase,
    isSavingAllDrafts,
    setIsSavingAllDrafts,
    caseSubmitError,
    setCaseSubmitError,
    navigate,
    caseSubmitToast,
    isLeaving,
    setIsLeaving,
    navError,
    setNavError,
    leaveGuardRef,
  };
}

export function useReviewerWorkspace(
  sourceView: import("../../../components/WorkspaceSourcePane").WorkspaceSourceView,
  setSourceView: React.Dispatch<
    React.SetStateAction<import("../../../components/WorkspaceSourcePane").WorkspaceSourceView>
  >,
) {
  const { tenantId = "", assignmentId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const campaignIdParam = searchParams.get("campaignId");
  const session = useAuthSession();
  // The AppLayout footer slot for this route's case navigation. Optional so the component still
  // renders if mounted outside the layout (defensive; the app always mounts it under AppLayout).
  const outletContext = useOutletContext<AppLayoutOutletContext | null>();
  const setFooterSlot = outletContext?.setFooterSlot;
  const {
    activeItemId,
    setActiveItemId,
    preserveSourceForItem,
    setPreserveSourceForItem,
    answers,
    setAnswers,
    lockVersions,
    setLockVersions,
    writeInFlightRef,
    openAdditionRef,
    pickingProvenance,
    setPickingProvenance,
    showShortcuts,
    setShowShortcuts,
    showSubmitPreview,
    setShowSubmitPreview,
    isSubmittingCase,
    setIsSubmittingCase,
    isSavingAllDrafts,
    setIsSavingAllDrafts,
    caseSubmitError,
    setCaseSubmitError,
    navigate,
    caseSubmitToast,
    isLeaving,
    setIsLeaving,
    navError,
    setNavError,
    leaveGuardRef,
  } = useReviewerWorkspaceState(sourceView, setSourceView);

  const {
    bundleQuery,
    campaignSummary,
    caseQueueQuery,
    documentHtml,
    htmlLoading,
    artifactAnchorUnavailable,
  } = useReviewerWorkspaceQueries(tenantId, assignmentId, campaignIdParam);
  const {
    additions,
    bundle,
    activeAddGroupId,
    setActiveAddGroupId,
    items,
    activeItem,
    activeGroup,
    activeAnswer,
    duplicateFeedback,
    completedCount,
  } = useReviewerWorkspaceSelection({
    bundleQuery,
    tenantId,
    assignmentId,
    session,
    answers,
    activeItemId,
  });
  const { orderedCases, currentCaseIndex, campaignQueueHref, caseTaskHref } =
    useReviewerCaseSession({
      caseQueueQuery,
      bundle,
      assignmentId,
      campaignIdParam,
      tenantId,
      setAnswers,
      openAdditionRef,
      setActiveItemId,
      setActiveAddGroupId,
      setPreserveSourceForItem,
      setLockVersions,
      additions,
      activeAddGroupId,
      setFooterSlot,
      isLeaving,
      leaveGuardRef,
    });
  const {
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
  } = useReviewerAnswerWrites({
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
  });
  const { startAddition, removeAddition } = useReviewerAdditionActions({
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
  });
  const { jumpToNextGroup, setValueAnswer, setProvenanceAnswer, handleProvenancePick } =
    useReviewerAnswerEditing({
      bundle,
      activeGroup,
      activeAddGroupId,
      selectItem,
      activeItem,
      activeAnswer,
      updateAnswer,
      setPickingProvenance,
    });

  useReviewerKeyboard({
    step: stepItem,
    nextGroup: jumpToNextGroup,
    value: setValueAnswer,
    provenance: setProvenanceAnswer,
    save: () => void saveCurrent(),
    submit: () => void submitCurrent(),
    mark: () => {
      if (
        activeItem?.reviewer_proposal ||
        (activeItem?.evidence_window_ids.length && activeAnswer?.provenance_correct === false)
      ) {
        setSourceView("text");
        setPickingProvenance((current) => !current);
      }
    },
    help: () => setShowShortcuts((current) => !current),
    escape: () => {
      setShowShortcuts(false);
      setShowSubmitPreview(false);
      setPickingProvenance(false);
    },
    added: Boolean(activeItem?.reviewer_proposal),
    editable: !activeAddGroupId && !activeAnswer?.submitted && !bundle?.case_submitted,
    ready: Boolean(
      activeAnswer &&
      (activeItem?.reviewer_proposal
        ? proposalReady(activeAnswer) && !duplicateFeedback.data?.conflicts?.length
        : activeAnswer.value_correct !== null &&
          activeAnswer.provenance_correct !== null &&
          !(
            activeAnswer.value_correct === false &&
            !activeAnswer.corrected_value.trim() &&
            !activeAnswer.comment.trim()
          )),
    ),
    modalOpen: showShortcuts || showSubmitPreview,
  });
  const { previewRows, hasUnsavedWork, saveAllDrafts, leaveTo, confirmCaseSubmit } =
    useReviewerCaseActions({
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
    });
  return {
    tenantId,
    campaignIdParam,
    preserveSourceForItem,
    answers,
    writeInFlightRef,
    sourceView,
    setSourceView,
    pickingProvenance,
    setPickingProvenance,
    showShortcuts,
    setShowShortcuts,
    showSubmitPreview,
    setShowSubmitPreview,
    isSubmittingCase,
    isSavingAllDrafts,
    caseSubmitError,
    setCaseSubmitError,
    caseSubmitToast,
    isLeaving,
    navError,
    setNavError,
    bundleQuery,
    campaignSummary,
    documentHtml,
    htmlLoading,
    artifactAnchorUnavailable,
    bundle,
    activeAddGroupId,
    setActiveAddGroupId,
    items,
    activeItem,
    activeGroup,
    activeAnswer,
    duplicateFeedback,
    completedCount,
    saveMutation,
    submitMutation,
    refreshAfterConflict,
    updateAnswer,
    saveCurrent,
    submitCurrent,
    openAssociatedItem,
    selectItem,
    startAddition,
    removeAddition,
    handleProvenancePick,
    previewRows,
    hasUnsavedWork,
    saveAllDrafts,
    leaveTo,
    confirmCaseSubmit,
  };
}
