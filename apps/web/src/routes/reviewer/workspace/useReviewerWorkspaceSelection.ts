import { useMemo, useState } from "react";
import { useAuthSession } from "../../../auth/authSession";
import { orderCitations } from "../citationOrdering";
import { emptyAnswer } from "../reviewerAnswerState";
import { allItems, findFirstItem, groupForItem } from "../reviewerWorkspaceSelectors";
import { useCitationDuplicates } from "../useCitationDuplicates";
import { useReviewerAdditions } from "../useReviewerAdditions";
import { useReviewerWorkspaceQueries } from "../useReviewerWorkspaceQueries";
import type { useReviewerWorkspaceState } from "./useReviewerWorkspace";

export function useReviewerWorkspaceSelection({
  bundleQuery,
  tenantId,
  assignmentId,
  session,
  answers,
  activeItemId,
}: {
  bundleQuery: ReturnType<typeof useReviewerWorkspaceQueries>["bundleQuery"];
  tenantId: string;
  assignmentId: string;
  session: ReturnType<typeof useAuthSession>;
  answers: ReturnType<typeof useReviewerWorkspaceState>["answers"];
  activeItemId: ReturnType<typeof useReviewerWorkspaceState>["activeItemId"];
}) {
  const additions = useReviewerAdditions(
    bundleQuery.data,
    tenantId,
    assignmentId,
    session.csrfToken,
  );
  const bundle = useMemo(
    () => orderCitations(additions.bundle, answers),
    [additions.bundle, answers],
  );
  const [activeAddGroupId, setActiveAddGroupId] = useState<string | null>(null);
  const items = useMemo(() => allItems(bundle), [bundle]);
  const activeItem =
    items.find((item) => item.review_unit_id === activeItemId) ??
    (activeAddGroupId ? null : findFirstItem(bundle));
  const activeGroup =
    groupForItem(bundle, activeItem) ??
    bundle?.field_groups.find((group) => group.group_id === activeAddGroupId) ??
    null;
  const activeAnswer = activeItem ? (answers[activeItem.review_unit_id] ?? emptyAnswer) : undefined;
  const duplicateFeedback = useCitationDuplicates(
    tenantId,
    activeItem,
    activeAnswer,
    session.csrfToken,
  );
  const completedCount = items.filter((item) => answers[item.review_unit_id]?.submitted).length;
  return {
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
  };
}
