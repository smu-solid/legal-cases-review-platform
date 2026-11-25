import { Spinner } from "../../../components/Spinner";
import { CaseProgressCard, WorkspaceCaseHeader } from "../../../components/WorkspaceCaseHeader";
import { AddedItemPanel } from "../AddedItemPanel";
import { AnswerPanel } from "../AnswerPanel";
import { CaseSubmitToast } from "../CaseSubmitToast";
import { GroupList } from "../GroupList";
import { KeyboardShortcutsModal } from "../KeyboardShortcutsModal";
import { ReviewerLeaveGuard } from "../ReviewerLeaveGuard";
import { SourcePane } from "../ReviewerWorkspacePanes";
import { SubmitPreviewModal } from "../SubmitPreviewModal";
import { describeMutationError } from "../reviewerAnswerState";
import { formatCaseTitle } from "../reviewerWorkspaceSelectors";
import type { useReviewerWorkspace } from "./useReviewerWorkspace";

type WorkspaceModel = ReturnType<typeof useReviewerWorkspace> & {
  bundle: NonNullable<ReturnType<typeof useReviewerWorkspace>["bundle"]>;
};

function ReviewerWorkspaceHeader({
  campaignIdParam,
  tenantId,
  campaignSummary,
  bundle,
  setShowShortcuts,
  completedCount,
  items,
  setShowSubmitPreview,
}: WorkspaceModel) {
  return (
    <WorkspaceCaseHeader
      backHref={
        campaignIdParam
          ? `/t/${tenantId}/review/campaigns/${campaignIdParam}`
          : `/t/${tenantId}/review`
      }
      backLabel="Back to campaign queue"
      campaignProgress={
        campaignSummary
          ? {
              completed: campaignSummary.completed_count,
              total:
                campaignSummary.not_started_count +
                campaignSummary.in_progress_count +
                campaignSummary.completed_count,
            }
          : null
      }
      eyebrow="Reviewer workspace"
      title={formatCaseTitle(bundle.case_header)}
      titleId="workspace-title"
      actions={
        <>
          <button
            className="secondary-button shortcuts-button"
            type="button"
            onClick={() => setShowShortcuts(true)}
          >
            Shortcuts (?)
          </button>
          <CaseProgressCard
            eyebrow="Case submit"
            completed={completedCount}
            total={items.length}
            action={
              <button
                className="primary-button"
                type="button"
                disabled={items.length === 0 || bundle.case_submitted}
                onClick={() => setShowSubmitPreview(true)}
              >
                {bundle.case_submitted ? "Case submitted" : "Review & submit case"}
              </button>
            }
          />
        </>
      }
    />
  );
}

function ReviewerWorkspaceContent({
  bundle,
  activeItem,
  answers,
  selectItem,
  startAddition,
  activeAddGroupId,
  setActiveAddGroupId,
  activeGroup,
  preserveSourceForItem,
  activeAnswer,
  openAssociatedItem,
  artifactAnchorUnavailable,
  documentHtml,
  htmlLoading,
  sourceView,
  setSourceView,
  pickingProvenance,
  handleProvenancePick,
  writeInFlightRef,
  isLeaving,
  isSavingAllDrafts,
  isSubmittingCase,
  duplicateFeedback,
  updateAnswer,
  saveCurrent,
  submitCurrent,
  removeAddition,
  setPickingProvenance,
  saveMutation,
  submitMutation,
  refreshAfterConflict,
}: WorkspaceModel) {
  return (
    <div className="workspace-grid">
      <GroupList
        groups={bundle.field_groups}
        activeItemId={activeItem?.review_unit_id ?? null}
        answers={answers}
        onSelect={selectItem}
        onAdd={startAddition}
        activeAddGroupId={activeAddGroupId}
        onAddFocus={setActiveAddGroupId}
      />
      <SourcePane
        bundle={bundle}
        activeGroupId={activeGroup?.group_id}
        preserveScroll={preserveSourceForItem === (activeItem?.review_unit_id ?? null)}
        activeItem={activeItem}
        activeAnswer={activeAnswer}
        answers={answers}
        onOpenItem={(id) => void openAssociatedItem(id)}
        artifactAnchorUnavailable={artifactAnchorUnavailable}
        documentHtml={documentHtml}
        htmlLoading={htmlLoading}
        view={sourceView}
        onViewChange={setSourceView}
        pickingProvenance={pickingProvenance}
        onProvenancePick={handleProvenancePick}
        onAddCitation={(charStart, charEnd) => {
          if (
            activeGroup?.group_id === "cited_cases" &&
            activeGroup.add_item_label &&
            bundle.proposal_source_version
          )
            startAddition(activeGroup, { charStart, charEnd });
        }}
        addingCitationDisabled={
          writeInFlightRef.current || isLeaving || isSavingAllDrafts || isSubmittingCase
        }
      />
      {activeItem?.reviewer_proposal && activeAnswer ? (
        <AddedItemPanel
          item={activeItem}
          duplicateFeedback={duplicateFeedback}
          onOpenExisting={(id) => void openAssociatedItem(id)}
          answer={activeAnswer}
          onChange={updateAnswer}
          onSave={() => void saveCurrent()}
          onSubmit={() => void submitCurrent()}
          onRemove={() => void removeAddition()}
          picking={pickingProvenance}
          onTogglePicking={() => {
            setSourceView("text");
            setPickingProvenance((current) => !current);
          }}
          busy={
            saveMutation.isPending ||
            submitMutation.isPending ||
            isLeaving ||
            isSavingAllDrafts ||
            isSubmittingCase
          }
          error={describeMutationError(saveMutation.error || submitMutation.error)}
          readOnly={Boolean(bundle.case_submitted || activeItem.status === "submitted")}
          onRefresh={refreshAfterConflict}
        />
      ) : (
        <AnswerPanel
          readOnly={Boolean(bundle.case_submitted)}
          activeItem={activeItem}
          answer={activeAnswer}
          onChange={updateAnswer}
          onSave={() => void saveCurrent()}
          onSubmit={() => void submitCurrent()}
          isSaving={saveMutation.isPending}
          isSubmitting={submitMutation.isPending}
          saveError={describeMutationError(saveMutation.error)}
          submitError={describeMutationError(submitMutation.error)}
          onRefresh={refreshAfterConflict}
          pickingProvenance={pickingProvenance}
          onTogglePicking={() => setPickingProvenance((current) => !current)}
        />
      )}
    </div>
  );
}

function ReviewerCaseSubmitPreview({
  bundle,
  campaignSummary,
  previewRows,
  isSubmittingCase,
  isSavingAllDrafts,
  caseSubmitError,
  setCaseSubmitError,
  setShowSubmitPreview,
  saveAllDrafts,
  setNavError,
  confirmCaseSubmit,
  refreshAfterConflict,
}: WorkspaceModel) {
  return (
    <SubmitPreviewModal
      caseTitle={formatCaseTitle(bundle.case_header)}
      campaignName={campaignSummary?.campaign_name ?? bundle.case_header.campaign_name ?? null}
      rows={previewRows}
      isSubmitting={isSubmittingCase}
      isSavingDrafts={isSavingAllDrafts}
      error={caseSubmitError}
      onCancel={() => {
        setCaseSubmitError(null);
        setShowSubmitPreview(false);
      }}
      onSaveAllDrafts={() =>
        void saveAllDrafts().catch(() =>
          setNavError("Drafts could not be saved. Your edits are still here."),
        )
      }
      onConfirm={() => void confirmCaseSubmit()}
      onRefresh={() => {
        setCaseSubmitError(null);
        refreshAfterConflict();
      }}
    />
  );
}

export function ReviewerWorkspaceView(model: WorkspaceModel) {
  const {
    showShortcuts,
    setShowShortcuts,
    showSubmitPreview,
    isSubmittingCase,
    caseSubmitToast,
    isLeaving,
    navError,
    bundleQuery,
    bundle,
    hasUnsavedWork,
    saveAllDrafts,
    leaveTo,
  } = model;
  return (
    <section
      className="reviewer-workspace"
      aria-labelledby="workspace-title"
      onClickCapture={(event) => {
        const link = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[href]");
        if (link && hasUnsavedWork && link.origin === window.location.origin) {
          event.preventDefault();
          event.stopPropagation();
          void leaveTo(link.pathname + link.search);
        }
      }}
    >
      <ReviewerWorkspaceHeader {...model} bundle={bundle} />

      {bundleQuery.isLoading ? (
        <div className="notice">
          <Spinner /> Loading grouped review bundle...
        </div>
      ) : null}
      {bundleQuery.isError ? (
        <div className="notice" role="alert">
          This review task could not be loaded right now. Retry in a moment, or contact an
          administrator if the problem continues.
        </div>
      ) : null}
      {navError ? (
        <div className="notice" role="alert">
          {navError}
        </div>
      ) : null}
      <CaseSubmitToast message={caseSubmitToast} />

      {/* Three panes only: the former standalone member-index column was removed -- the left group
          list already expands the active repeatable group with the same dot + citation rows, so the
          index duplicated navigation and cost the source pane ~240px of width. */}
      <ReviewerWorkspaceContent {...model} bundle={bundle} />

      <ReviewerLeaveGuard
        dirty={hasUnsavedWork && !isLeaving && !isSubmittingCase}
        save={saveAllDrafts}
      />
      {showShortcuts ? <KeyboardShortcutsModal onClose={() => setShowShortcuts(false)} /> : null}
      {showSubmitPreview ? <ReviewerCaseSubmitPreview {...model} bundle={bundle} /> : null}
    </section>
  );
}
