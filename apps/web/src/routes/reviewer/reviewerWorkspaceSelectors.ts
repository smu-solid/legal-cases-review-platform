import type { GroupItem, ReviewerGroupingBundle } from "../../api/types";
export function allItems(bundle: ReviewerGroupingBundle | undefined): GroupItem[] {
  return bundle?.field_groups.flatMap((group) => group.items) ?? [];
}

export function findFirstItem(bundle: ReviewerGroupingBundle | undefined) {
  return bundle?.field_groups[0]?.items[0] ?? null;
}

export function formatCaseTitle(caseHeader: ReviewerGroupingBundle["case_header"]) {
  return [
    caseHeader.neutral_citation_display,
    caseHeader.case_title,
    caseHeader.reported_citation_display,
  ]
    .filter((part): part is string => Boolean(part && part.trim()))
    .join(" · ");
}

export function groupForItem(bundle: ReviewerGroupingBundle | undefined, item: GroupItem | null) {
  if (!bundle || !item) {
    return null;
  }
  return bundle.field_groups.find((group) => group.items.includes(item)) ?? null;
}
