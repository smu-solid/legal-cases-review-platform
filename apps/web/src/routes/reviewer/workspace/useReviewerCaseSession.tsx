import type { ReactNode } from "react";
import { useEffect, useMemo } from "react";
import { CaseFooterNav } from "../ReviewerWorkspacePanes";
import { orderCitations } from "../citationOrdering";
import { mergeHydratedAnswers } from "../reviewerAnswerState";
import { findFirstItem } from "../reviewerWorkspaceSelectors";
import { useReviewerWorkspaceQueries } from "../useReviewerWorkspaceQueries";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";
import { useReviewerWorkspaceSelection } from "./useReviewerWorkspaceSelection";

export function useReviewerCaseSession({
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
}: {
  caseQueueQuery: ReturnType<typeof useReviewerWorkspaceQueries>["caseQueueQuery"];
  bundle: ReturnType<typeof useReviewerWorkspaceSelection>["bundle"];
  assignmentId: string;
  campaignIdParam: string | null;
  tenantId: string;
  setAnswers: ReturnType<typeof useReviewerWorkspaceState>["setAnswers"];
  openAdditionRef: ReturnType<typeof useReviewerWorkspaceState>["openAdditionRef"];
  setActiveItemId: ReturnType<typeof useReviewerWorkspaceState>["setActiveItemId"];
  setActiveAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["setActiveAddGroupId"];
  setPreserveSourceForItem: ReturnType<
    typeof useReviewerWorkspaceState
  >["setPreserveSourceForItem"];
  setLockVersions: ReturnType<typeof useReviewerWorkspaceState>["setLockVersions"];
  additions: ReturnType<typeof useReviewerWorkspaceSelection>["additions"];
  activeAddGroupId: ReturnType<typeof useReviewerWorkspaceSelection>["activeAddGroupId"];
  setFooterSlot: ((node: ReactNode) => void) | undefined;
  isLeaving: ReturnType<typeof useReviewerWorkspaceState>["isLeaving"];
  leaveGuardRef: ReturnType<typeof useReviewerWorkspaceState>["leaveGuardRef"];
}) {
  // The within-campaign ordered case list and this case's position in it -- shared by the footer
  // Previous/Next nav effect below and by confirmCaseSubmit's post-submit auto-navigation, so both
  // agree on "the next case" without recomputing the lookup twice. Memoized (not just `?? []`) so
  // its reference is stable across renders where the underlying query data hasn't changed --
  // otherwise a fresh `[]` every render would re-trigger the effects that depend on it.
  const orderedCases = useMemo(() => caseQueueQuery.data?.items ?? [], [caseQueueQuery.data]);
  const currentCaseIndex = useMemo(() => {
    // The fast path matches the route's `anchor_assignment_id`, but a reviewer who entered via a
    // *non-anchor* field assignment (a freshly claimed field) has an assignmentId that is no case's
    // anchor -- so fall back to matching the loaded case by its stable identity (title +
    // neutral/reported citation, from the bundle header) rather than failing to locate it.
    const header = bundle?.case_header;
    return orderedCases.findIndex(
      (item) =>
        item.anchor_assignment_id === assignmentId ||
        (header != null &&
          item.case_title === header.case_title &&
          (item.neutral_citation_display ?? null) === (header.neutral_citation_display ?? null) &&
          (item.reported_citation_display ?? null) === (header.reported_citation_display ?? null)),
    );
  }, [orderedCases, bundle, assignmentId]);
  const campaignQueueHref = campaignIdParam
    ? `/t/${tenantId}/review/campaigns/${campaignIdParam}`
    : `/t/${tenantId}/review`;
  const caseTaskHref = (targetAssignmentId: string) =>
    `/t/${tenantId}/review/task/${targetAssignmentId}${campaignIdParam ? `?campaignId=${campaignIdParam}` : ""}`;

  // A new assignment (route change) starts from a clean slate; a refetch of the *same* assignment
  // (e.g. the "refresh and retry" action after a stale-write conflict) must not discard whatever
  // the reviewer already typed, so that path is handled by the merge effect below instead.
  useEffect(() => {
    setAnswers({});
    openAdditionRef.current = null;
    setActiveItemId(null);
    setActiveAddGroupId(null);
    setPreserveSourceForItem(undefined);
    setLockVersions({});
  }, [
    assignmentId,
    openAdditionRef,
    setActiveAddGroupId,
    setActiveItemId,
    setAnswers,
    setLockVersions,
    setPreserveSourceForItem,
  ]);

  useEffect(() => {
    if (!additions.bundle) return;
    const loaded = additions.bundle;
    setAnswers((current) => mergeHydratedAnswers(loaded, current));
    setActiveItemId(
      (current) =>
        current ??
        (activeAddGroupId
          ? null
          : (findFirstItem(orderCitations(loaded, {}))?.review_unit_id ?? null)),
    );
  }, [additions.bundle, activeAddGroupId, setAnswers, setActiveItemId]);

  // Publish this case's within-campaign Previous/Next navigation into the fixed footer, and clear it
  // when the workspace unmounts (so the campaign case-list and home pages show a brand-only footer).
  useEffect(() => {
    if (!setFooterSlot) {
      return;
    }
    const prev = currentCaseIndex > 0 ? orderedCases[currentCaseIndex - 1] : null;
    const next =
      currentCaseIndex >= 0 && currentCaseIndex < orderedCases.length - 1
        ? orderedCases[currentCaseIndex + 1]
        : null;
    setFooterSlot(
      <CaseFooterNav
        tenantId={tenantId}
        campaignId={campaignIdParam}
        prevAssignmentId={prev?.anchor_assignment_id ?? null}
        nextAssignmentId={next?.anchor_assignment_id ?? null}
        isLeaving={isLeaving}
        onLeave={(to) => leaveGuardRef.current(to)}
      />,
    );
    return () => setFooterSlot(null);
  }, [
    setFooterSlot,
    orderedCases,
    currentCaseIndex,
    tenantId,
    campaignIdParam,
    isLeaving,
    leaveGuardRef,
  ]);
  return { orderedCases, currentCaseIndex, campaignQueueHref, caseTaskHref };
}
