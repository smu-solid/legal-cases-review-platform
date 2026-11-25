import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import type { MembershipChange, ProposalSpan } from "../../../api/proposalAdjudication";
import type { ReviewerLeaveGuard } from "../../reviewer/ReviewerLeaveGuard";
import type { AdjudicationDraftRecovery } from "../AdjudicationDraftRecovery";
import { mergeProposalWorkspace } from "../adjudicationProposals";
import type { AdjudicationWorkspaceContentProps } from "../AdjudicationWorkspaceContent";
import { useProposalAdjudication } from "../useProposalAdjudication";

import {
  getAdjudicationCaseNeighbors,
  getAdjudicationCaseWorkspace,
  getAdjudicationSourceRenderAnchors,
  getAdjudicationSourceRenderBody,
  getAdjudicationSourceRenderMetadata,
  saveAdjudicationDraft,
  submitAdjudicationDecision,
} from "../../../api/admin";
import type { AdjudicationCampaignCaseItem, AdjudicationWorkspaceItem } from "../../../api/types";
import { useAuthSession } from "../../../auth/authSession";
import type { WorkspaceSourceView } from "../../../components/WorkspaceSourcePane";
import type { AppLayoutOutletContext } from "../../../layout/AppLayout";
import { matchesAgreementFilter, type AgreementStatus } from "../adjudicationAgreement";
import {
  adjudicationDecisionReady,
  adjudicationDraftReady,
  buildAdjudicationDecision,
  buildAdjudicationDraft,
  hydrateAdjudicationDecision,
  type LocalAdjudicationDecision,
} from "../adjudicationDecisionState";
import { useAdjudicationFooter } from "../useAdjudicationFooter";
import { useAdjudicationKeyboard } from "../useAdjudicationKeyboard";

type DecisionMap = Record<string, LocalAdjudicationDecision>;
type MutationVars = { item: AdjudicationWorkspaceItem; local: LocalAdjudicationDecision };

export function useAdjudicationWorkspace() {
  const { tenantId = "", adjudicationId = "" } = useParams();
  const [search] = useSearchParams();
  const campaignIdHint = search.get("campaignId") ?? "";
  const session = useAuthSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setFooterSlot } = useOutletContext<AppLayoutOutletContext>();
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<DecisionMap>({});
  const [filter, setFilter] = useState<AgreementStatus>("all");
  const [sourceView, setSourceView] = useState<WorkspaceSourceView>("text");
  const [pickingProvenance, setPickingProvenance] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showSubmitPreview, setShowSubmitPreview] = useState(false);
  const [caseBusy, setCaseBusy] = useState<"saving" | "submitting" | null>(null);
  const [caseError, setCaseError] = useState<string | null>(null);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);

  const workspaceQuery = useQuery({
    queryKey: ["adjudication-case-workspace", tenantId, adjudicationId],
    queryFn: () => getAdjudicationCaseWorkspace(tenantId, adjudicationId),
    enabled: Boolean(tenantId && adjudicationId),
    retry: false,
  });
  const proposals = useProposalAdjudication(
    tenantId,
    adjudicationId,
    workspaceQuery.data,
    session.csrfToken,
  );
  const bundle = proposals.bundle;
  const writeProposal = proposals.write;
  const [focusedSpan, setFocusedSpan] = useState<(ProposalSpan & { label: string }) | null>(null);
  const fieldAction = useRef(false);
  const caseAction = useRef(false);
  const campaignId = bundle?.campaign.campaign_id ?? campaignIdHint;
  const allItems = useMemo(
    () => bundle?.field_groups.flatMap((group) => group.items) ?? [],
    [bundle],
  );
  const groups = useMemo(
    () =>
      bundle?.field_groups
        .map((group) => ({
          ...group,
          items: group.items.filter((item) => matchesAgreementFilter(item, filter)),
        }))
        .filter((group) => group.items.length) ?? [],
    [bundle, filter],
  );
  const visibleItems = useMemo(() => groups.flatMap((group) => group.items), [groups]);
  const activeItem =
    visibleItems.find((item) => item.item_id === activeItemId) ??
    visibleItems.find((item) => item.participation_status === "pending") ??
    visibleItems[0] ??
    null;
  const activeLocal = activeItem ? decisions[activeItem.item_id] : undefined;
  const editable = bundle?.mode === "edit" && activeItem?.participation_status === "pending";

  useEffect(() => {
    if (!bundle) return;
    setDecisions((current) => ({
      ...current,
      ...Object.fromEntries(
        allItems.map((item) => {
          const local = current[item.item_id];
          return [
            item.item_id,
            local?.dirty ? local : hydrateAdjudicationDecision(item, bundle.source_render.content),
          ];
        }),
      ),
    }));
  }, [allItems, bundle]);
  useEffect(() => {
    setActiveItemId(null);
    setDecisions({});
    setSourceView("text");
    setPickingProvenance(false);
    setSubmissionMessage(null);
  }, [adjudicationId]);

  const sourceMetaQuery = useQuery({
    queryKey: ["adjudication-source-render-meta", tenantId, adjudicationId],
    queryFn: () => getAdjudicationSourceRenderMetadata(tenantId, adjudicationId),
    enabled: Boolean(tenantId && adjudicationId),
    retry: false,
  });
  const hasHtmlArtifact =
    sourceMetaQuery.data?.render_mode === "sanitized_html" &&
    sourceMetaQuery.data.artifact_mime_type === "text/html";
  const sourceBodyQuery = useQuery({
    queryKey: [
      "adjudication-source-render-body",
      tenantId,
      adjudicationId,
      activeItem?.review_unit_id,
    ],
    queryFn: () =>
      getAdjudicationSourceRenderBody(
        tenantId,
        adjudicationId,
        activeItem?.document_unit_id ?? activeItem?.review_unit_id ?? "",
      ),
    enabled: Boolean(tenantId && adjudicationId && activeItem?.review_unit_id && hasHtmlArtifact),
    retry: false,
  });
  const sourceAnchorsQuery = useQuery({
    queryKey: ["adjudication-source-render-anchors", tenantId, adjudicationId],
    queryFn: () => getAdjudicationSourceRenderAnchors(tenantId, adjudicationId),
    enabled: Boolean(tenantId && adjudicationId && hasHtmlArtifact),
    retry: false,
  });
  const neighborsQuery = useQuery({
    queryKey: ["adjudication-neighbors", tenantId, campaignId, adjudicationId],
    queryFn: () => getAdjudicationCaseNeighbors(tenantId, campaignId, adjudicationId),
    enabled: Boolean(tenantId && campaignId && adjudicationId),
    retry: false,
  });

  const saveMutation = useMutation<unknown, Error, MutationVars>({
    mutationFn: ({ item, local }: MutationVars) =>
      item.proposal_item
        ? proposals.write(item, local, false)
        : saveAdjudicationDraft(
            tenantId,
            item.adjudication_id,
            buildAdjudicationDraft(item, local),
            session.csrfToken,
          ),
  });
  const submitMutation = useMutation<unknown, Error, MutationVars>({
    mutationFn: ({ item, local }: MutationVars) =>
      item.proposal_item
        ? proposals.write(item, local, true)
        : submitAdjudicationDecision(
            tenantId,
            item.adjudication_id,
            buildAdjudicationDecision(item, local),
            session.csrfToken,
          ),
  });

  function updateActive(partial: Partial<LocalAdjudicationDecision>) {
    if (!activeItem || !editable) return;
    if (partial.verdict && partial.verdict !== "all_wrong") setPickingProvenance(false);
    setDecisions((current) => {
      const local =
        current[activeItem.item_id] ??
        hydrateAdjudicationDecision(activeItem, bundle?.source_render.content ?? "");
      return {
        ...current,
        [activeItem.item_id]: { ...local, ...partial, dirty: true, saved: false },
      };
    });
  }
  async function saveOne(item: AdjudicationWorkspaceItem, local: LocalAdjudicationDecision) {
    await saveMutation.mutateAsync({ item, local });
    setDecisions((current) => ({
      ...current,
      [item.item_id]: {
        ...current[item.item_id],
        saved: current[item.item_id] === local,
        dirty: current[item.item_id] !== local,
        proposalVersion: item.proposal_item
          ? (local.proposalVersion ?? item.proposal_item.lock_version) + 1
          : undefined,
      },
    }));
  }
  async function refreshAfterSubmit(item: AdjudicationWorkspaceItem) {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["adjudication-campaign-cases", tenantId, campaignId],
      }),
      queryClient.invalidateQueries({ queryKey: ["adjudication-campaigns", tenantId] }),
      queryClient.invalidateQueries({
        queryKey: ["adjudication-neighbors", tenantId, campaignId, adjudicationId],
      }),
    ]);
    const refreshed = await workspaceQuery.refetch();
    const extra = await proposals.query.refetch();
    const next = mergeProposalWorkspace(refreshed.data, extra.data)
      ?.field_groups.flatMap((group) => group.items)
      .find((candidate) => candidate.participation_status === "pending");
    setActiveItemId(next?.item_id ?? item.item_id);
    setSubmissionMessage(
      next
        ? `Decision submitted. Continuing with ${next.item_label}.`
        : "Case adjudication complete. Submitted decisions are read-only.",
    );
  }
  async function submitOne(item: AdjudicationWorkspaceItem, local: LocalAdjudicationDecision) {
    await submitMutation.mutateAsync({ item, local });
    setDecisions((current) => ({
      ...current,
      [item.item_id]: { ...current[item.item_id], submitted: true, saved: true, dirty: false },
    }));
  }
  async function saveCurrent() {
    if (
      fieldAction.current ||
      !activeItem ||
      !activeLocal ||
      !adjudicationDraftReady(activeItem, activeLocal) ||
      !editable
    )
      return;
    fieldAction.current = true;
    setNavigationError(null);
    try {
      await saveOne(activeItem, activeLocal);
    } catch {
      setNavigationError(
        "Draft rejected. Your input is retained. Refresh to check for membership changes.",
      );
    } finally {
      fieldAction.current = false;
    }
  }
  async function submitCurrent() {
    if (
      fieldAction.current ||
      !activeItem ||
      !activeLocal ||
      !editable ||
      !adjudicationDecisionReady(activeItem, activeLocal)
    )
      return;
    fieldAction.current = true;
    setNavigationError(null);
    try {
      await submitOne(activeItem, activeLocal);
      await refreshAfterSubmit(activeItem);
    } catch {
      setNavigationError(
        "Submission rejected. Your input is retained. Refresh and reassess the current item.",
      );
    } finally {
      fieldAction.current = false;
    }
  }

  const moveTo = useCallback(
    async (target: AdjudicationCampaignCaseItem | null | undefined) => {
      if (!target?.workspace_adjudication_id) return;
      setNavigationError(null);
      try {
        if (
          activeItem &&
          activeLocal?.dirty &&
          adjudicationDraftReady(activeItem, activeLocal) &&
          editable
        ) {
          if (activeItem.proposal_item) await writeProposal(activeItem, activeLocal, false);
          else
            await saveAdjudicationDraft(
              tenantId,
              activeItem.adjudication_id,
              buildAdjudicationDraft(activeItem, activeLocal),
              session.csrfToken,
            );
        }
        navigate(
          `/t/${tenantId}/adjudication/${target.workspace_adjudication_id}?campaignId=${campaignId}`,
        );
      } catch {
        setNavigationError("Your draft could not be saved, so navigation was stopped.");
      }
    },
    [
      activeItem,
      activeLocal,
      campaignId,
      editable,
      navigate,
      session.csrfToken,
      tenantId,
      writeProposal,
    ],
  );

  const previewRows = allItems.map((item) => {
    const decision =
      decisions[item.item_id] ??
      hydrateAdjudicationDecision(item, bundle?.source_render.content ?? "");
    return { item, decision, ready: adjudicationDecisionReady(item, decision) };
  });
  async function saveAllDrafts() {
    setCaseBusy("saving");
    setCaseError(null);
    try {
      for (const row of previewRows.filter(
        (entry) => !entry.decision.submitted && entry.decision.dirty,
      ))
        await saveOne(row.item, row.decision);
    } catch {
      setCaseError("One or more drafts could not be saved.");
    } finally {
      setCaseBusy(null);
    }
  }
  async function confirmCaseSubmit() {
    if (caseAction.current || !proposals.query.data || proposals.query.isError) return;
    caseAction.current = true;
    setCaseBusy("submitting");
    setCaseError(null);
    let last: AdjudicationWorkspaceItem | null = null;
    try {
      for (const row of previewRows.filter((entry) => !entry.decision.submitted)) {
        await submitOne(row.item, row.decision);
        last = row.item;
      }
      setShowSubmitPreview(false);
      if (last) await refreshAfterSubmit(last);
    } catch {
      setCaseError(
        "A field could not be submitted. Unsaved input is retained; submitted fields remain final.",
      );
    } finally {
      caseAction.current = false;
      setCaseBusy(null);
    }
  }

  useAdjudicationKeyboard({
    activeItem,
    activeDecision: activeLocal,
    editable: Boolean(editable),
    visibleItems,
    bundle,
    onUpdate: updateActive,
    onSelect: (id) => {
      setActiveItemId(id);
      setFocusedSpan(null);
      setPickingProvenance(false);
    },
    onSave: () => void saveCurrent(),
    onSubmit: () => void submitCurrent(),
    onTogglePicking: () => {
      setSourceView("text");
      setPickingProvenance((current) => !current);
    },
    onToggleShortcuts: () => setShowShortcuts((current) => !current),
    onDismiss: () => {
      setShowShortcuts(false);
      setShowSubmitPreview(false);
      setPickingProvenance(false);
    },
  });

  useAdjudicationFooter({
    tenantId,
    campaignId,
    neighbors: neighborsQuery.data,
    completed: bundle?.mode === "read_only",
    saving: saveMutation.isPending,
    setFooterSlot,
    onMove: moveTo,
  });

  const loadState =
    workspaceQuery.isLoading || workspaceQuery.isError
      ? {
          loading: workspaceQuery.isLoading,
          error: workspaceQuery.error,
          tenantId,
          campaignId: campaignIdHint,
        }
      : null;
  if (loadState || !bundle) return { loadState, workspace: null };
  const submittedCount = allItems.filter(
    (item) => decisions[item.item_id]?.submitted ?? item.participation_status === "submitted",
  ).length;

  const canSave = Boolean(
    editable &&
    activeItem &&
    activeLocal &&
    adjudicationDraftReady(activeItem, activeLocal) &&
    (activeItem.proposal_item || activeItem.submissions.length >= activeItem.required_reviews),
  );

  const canSubmit = Boolean(
    activeItem && activeLocal && adjudicationDecisionReady(activeItem, activeLocal),
  );

  const content: Omit<AdjudicationWorkspaceContentProps, "proposalControls"> = {
    tenantId,
    campaignId,
    bundle,
    allItems,
    groups,
    focusedProposalSpan: focusedSpan,
    onShowProposalSpan: (span, label) => {
      setFocusedSpan({ ...span, label });
      setSourceView("text");
    },
    filter,
    activeItem,
    activeDecision: activeLocal,
    adjudicatorLabel: session.me?.display_name?.trim() || session.me?.email || "Adjudicator",
    submittedCount,
    navigationError,
    submissionMessage,
    source: {
      hasDocument: hasHtmlArtifact,
      documentHtml: sourceBodyQuery.data ?? null,
      loading: Boolean(hasHtmlArtifact && sourceBodyQuery.isLoading),
      anchorsUnavailable: Boolean(hasHtmlArtifact && sourceAnchorsQuery.isError),
      view: sourceView,
      picking: pickingProvenance,
    },
    mutation: {
      canSave,
      canSubmit,
      saving: saveMutation.isPending,
      saveError: saveMutation.isError,
      saveSuccess: saveMutation.isSuccess,
      submitting: submitMutation.isPending,
      submitError: submitMutation.isError,
    },
    preview: {
      visible: showSubmitPreview,
      rows: previewRows,
      busy: caseBusy,
      error: caseError,
    },
    shortcutsVisible: showShortcuts,
    onFilterChange: (value) => {
      setFilter(value);
      setActiveItemId(null);
    },
    onSelect: (id) => {
      setActiveItemId(id);
      setFocusedSpan(null);
      setPickingProvenance(false);
    },
    onSourceViewChange: setSourceView,
    onProvenancePick: (start, end) => {
      if (!activeItem || !activeLocal || activeLocal.verdict !== "all_wrong") return;
      const evidenceWindowId =
        activeItem.evidence_window_ids[0] ??
        (activeItem.proposal_item ? activeItem.review_unit_id : null);
      if (!evidenceWindowId) return;
      updateActive({
        proposalSource: activeItem.proposal_source,
        correctedProvenanceSpans: [
          ...(activeItem.proposal_item ? activeLocal.correctedProvenanceSpans : []),
          {
            evidence_window_id: evidenceWindowId,
            char_start: start,
            char_end: end,
            selected_text: bundle.source_render.content.slice(start, end),
          },
        ],
      });
      setPickingProvenance(false);
    },
    onUpdate: updateActive,
    onTogglePicking: () => {
      setSourceView("text");
      setPickingProvenance((current) => !current);
    },
    onSave: () => void saveCurrent(),
    onSubmit: () => void submitCurrent(),
    onOpenShortcuts: () => setShowShortcuts(true),
    onCloseShortcuts: () => setShowShortcuts(false),
    onOpenPreview: () => {
      if (proposals.query.data && !proposals.query.isError) setShowSubmitPreview(true);
      else
        setNavigationError(
          "Load reviewer-added items before submitting the case. Refresh to retry.",
        );
    },
    onClosePreview: () => {
      setCaseError(null);
      setShowSubmitPreview(false);
    },
    onSaveAll: () => void saveAllDrafts(),
    onConfirmAll: () => void confirmCaseSubmit(),
  };
  return {
    loadState,
    workspace: {
      content,
      leaveGuard: {
        dirty: Object.values(decisions).some((d) => d.dirty && !d.submitted),
        save: async () => {
          for (const [id, local] of Object.entries(decisions)) {
            if (!local.dirty || local.submitted) continue;
            const item = allItems.find((i) => i.item_id === id);
            if (!item) throw new Error("Reassess retained drafts before leaving.");
            await saveOne(item, local);
          }
        },
      } satisfies ComponentProps<typeof ReviewerLeaveGuard>,
      recovery: {
        items: allItems,
        drafts: decisions,
        active: activeItem,
        onRefresh: () => {
          void workspaceQuery.refetch();
          void proposals.query.refetch();
        },
        onReassess: () => {
          if (activeItem)
            updateActive({
              proposalVersion: activeItem.proposal_item?.lock_version,
              membershipVersion: activeItem.membership_version ?? 0,
            });
        },
        onRestore: (id) => {
          if (!activeItem) return;
          setDecisions((current) => {
            const next = { ...current };
            delete next[id];
            next[activeItem.item_id] = {
              ...current[id],
              dirty: true,
              saved: false,
              submitted: false,
              proposalVersion: activeItem.proposal_item?.lock_version,
              membershipVersion: activeItem.membership_version ?? 0,
            };
            return next;
          });
        },
      } satisfies ComponentProps<typeof AdjudicationDraftRecovery>,
      proposalError: proposals.query.isError,
      onMembershipChange: async (body: MembershipChange) => {
        const affected = allItems.filter(
          (i) =>
            i.proposal_item?.id === body.item_id ||
            (Boolean(body.target_item_id) && i.proposal_item?.id === body.target_item_id) ||
            i.adjudication_id === body.target_extracted_id,
        );
        await proposals.change(body);
        setDecisions((current) => {
          const next = { ...current };
          for (const i of affected) delete next[i.item_id];
          return next;
        });
        setActiveItemId(null);
        setFocusedSpan(null);
      },
    },
  };
}
