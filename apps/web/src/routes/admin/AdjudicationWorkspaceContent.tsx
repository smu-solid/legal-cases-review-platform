import type { ReactNode } from "react";
import type { ProposalSpan } from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import { CaseProgressCard, WorkspaceCaseHeader } from "../../components/WorkspaceCaseHeader";
import type { WorkspaceSourceView } from "../../components/WorkspaceSourcePane";
import type { AgreementStatus } from "./adjudicationAgreement";
import {
  AdjudicationShortcutsModal,
  AdjudicationSubmitPreviewModal,
  type AdjudicationPreviewRow,
} from "./AdjudicationCaseActions";
import { AdjudicationDecisionPane } from "./AdjudicationDecisionPane";
import {
  formatAdjudicationCaseTitle,
  verdictOptions,
  type LocalAdjudicationDecision,
} from "./adjudicationDecisionState";
import { AdjudicationFieldNav } from "./AdjudicationFieldNav";
import { AdjudicationSourcePane } from "./AdjudicationSourcePane";

type Groups = AdjudicationCaseWorkspace["field_groups"];

export interface AdjudicationWorkspaceContentProps {
  proposalControls?: ReactNode;
  focusedProposalSpan?: (ProposalSpan & { label: string }) | null;
  onShowProposalSpan?: (span: ProposalSpan, label: string) => void;
  tenantId: string;
  campaignId: string;
  bundle: AdjudicationCaseWorkspace;
  allItems: AdjudicationWorkspaceItem[];
  groups: Groups;
  filter: AgreementStatus;
  activeItem: AdjudicationWorkspaceItem | null;
  activeDecision: LocalAdjudicationDecision | undefined;
  adjudicatorLabel: string;
  submittedCount: number;
  navigationError: string | null;
  submissionMessage: string | null;
  source: {
    hasDocument: boolean;
    documentHtml: string | null;
    loading: boolean;
    anchorsUnavailable: boolean;
    view: WorkspaceSourceView;
    picking: boolean;
  };
  mutation: {
    canSave: boolean;
    canSubmit: boolean;
    saving: boolean;
    saveError: boolean;
    saveSuccess: boolean;
    submitting: boolean;
    submitError: boolean;
  };
  preview: {
    visible: boolean;
    rows: AdjudicationPreviewRow[];
    busy: "saving" | "submitting" | null;
    error: string | null;
  };
  shortcutsVisible: boolean;
  onFilterChange: (filter: AgreementStatus) => void;
  onSelect: (itemId: string) => void;
  onSourceViewChange: (view: WorkspaceSourceView) => void;
  onProvenancePick: (start: number, end: number) => void;
  onUpdate: (partial: Partial<LocalAdjudicationDecision>) => void;
  onTogglePicking: () => void;
  onSave: () => void;
  onSubmit: () => void;
  onOpenShortcuts: () => void;
  onCloseShortcuts: () => void;
  onOpenPreview: () => void;
  onClosePreview: () => void;
  onSaveAll: () => void;
  onConfirmAll: () => void;
}

export function AdjudicationWorkspaceContent(props: AdjudicationWorkspaceContentProps) {
  const { activeDecision, activeItem, bundle } = props;
  const editable = bundle.mode === "edit" && activeItem?.participation_status === "pending";
  const options = activeItem ? verdictOptions(activeItem) : [];
  return (
    <section className="reviewer-workspace" aria-labelledby="adjudication-workspace-title">
      <WorkspaceCaseHeader
        backHref={`/t/${props.tenantId}/adjudication/campaigns/${props.campaignId}`}
        backLabel="Back to campaign cases"
        campaignProgress={{
          completed: bundle.campaign.finished_count,
          total: bundle.campaign.total_case_count,
        }}
        eyebrow="Adjudication workspace"
        title={formatAdjudicationCaseTitle(bundle.case_header)}
        titleId="adjudication-workspace-title"
        actions={
          <>
            <button
              className="secondary-button shortcuts-button"
              type="button"
              onClick={props.onOpenShortcuts}
            >
              Shortcuts (?)
            </button>
            <CaseProgressCard
              eyebrow="Case submit"
              completed={props.submittedCount}
              total={props.allItems.length}
              action={
                <button
                  className="primary-button"
                  type="button"
                  disabled={!props.allItems.length}
                  onClick={props.onOpenPreview}
                >
                  Review &amp; submit case
                </button>
              }
            />
          </>
        }
      />
      {props.navigationError ? (
        <div className="notice" role="alert">
          {props.navigationError}
        </div>
      ) : null}
      {props.submissionMessage ? (
        <div className="notice compact" role="status">
          {props.submissionMessage}
        </div>
      ) : bundle.mode === "read_only" ? (
        <div className="notice compact" role="status">
          Your adjudication for this case is complete. Submitted decisions are read-only.
        </div>
      ) : null}
      <div className="workspace-grid adjudication-grid">
        <AdjudicationFieldNav
          groups={props.groups}
          activeItem={activeItem}
          filter={props.filter}
          onFilterChange={props.onFilterChange}
          onSelect={props.onSelect}
        />
        <AdjudicationSourcePane
          focusedProposalSpan={props.focusedProposalSpan}
          caseTitle={bundle.case_header.case_title}
          sourceRender={bundle.source_render}
          activeItem={activeItem}
          documentHtml={props.source.hasDocument ? props.source.documentHtml : null}
          htmlLoading={props.source.loading}
          artifactAnchorUnavailable={props.source.anchorsUnavailable}
          view={props.source.view}
          onViewChange={props.onSourceViewChange}
          adjudicatorSpans={activeDecision?.correctedProvenanceSpans ?? []}
          adjudicatorLabel={props.adjudicatorLabel}
          pickingProvenance={props.source.picking}
          onProvenancePick={props.onProvenancePick}
        />
        <AdjudicationDecisionPane
          activeItem={activeItem}
          proposalControls={props.proposalControls}
          onShowProposalSpan={props.onShowProposalSpan}
          sourceContent={bundle.source_render.content}
          editable={Boolean(editable)}
          verdict={activeDecision?.verdict ?? null}
          correctedValue={activeDecision?.correctedValue ?? ""}
          comment={activeDecision?.comment ?? ""}
          correctedProvenanceSpans={activeDecision?.correctedProvenanceSpans ?? []}
          pickingProvenance={props.source.picking}
          commentRequired={Boolean(
            activeDecision?.verdict &&
            ["all_wrong", "unsupported_or_not_locatable", "exceptional_skip"].includes(
              activeDecision.verdict,
            ),
          )}
          {...props.mutation}
          onVerdictChange={(verdict) =>
            props.onUpdate({
              verdict,
              correctedProvenanceSpans:
                verdict === "all_wrong" ? (activeDecision?.correctedProvenanceSpans ?? []) : [],
            })
          }
          onCorrectedValueChange={(correctedValue) => props.onUpdate({ correctedValue })}
          onCommentChange={(comment) => props.onUpdate({ comment })}
          onToggleProvenancePicking={props.onTogglePicking}
          onClearProvenance={(index) =>
            props.onUpdate({
              correctedProvenanceSpans: (activeDecision?.correctedProvenanceSpans ?? []).filter(
                (_, itemIndex) => itemIndex !== index,
              ),
            })
          }
          onSave={props.onSave}
          onSubmit={props.onSubmit}
        />
      </div>
      {props.shortcutsVisible ? (
        <AdjudicationShortcutsModal options={options} onClose={props.onCloseShortcuts} />
      ) : null}
      {props.preview.visible ? (
        <AdjudicationSubmitPreviewModal
          caseTitle={formatAdjudicationCaseTitle(bundle.case_header)}
          campaignName={bundle.campaign.campaign_name}
          rows={props.preview.rows}
          busy={props.preview.busy}
          error={props.preview.error}
          onCancel={props.onClosePreview}
          onSaveAll={props.onSaveAll}
          onConfirm={props.onConfirmAll}
        />
      ) : null}
    </section>
  );
}
