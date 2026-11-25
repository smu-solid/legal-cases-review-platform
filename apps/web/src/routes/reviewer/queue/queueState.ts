import type { ReviewerCaseQueueItem, ReviewQueueItem } from "../../../api/types";

export const STATUS_LABEL: Record<ReviewerCaseQueueItem["status"], string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
};

export const CASE_PAGE_SIZES = [5, 10, 20, 50] as const;

export const DEFAULT_CASE_PAGE_SIZE = 10;

export function pageWindow(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  const ordered = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  let previous = 0;
  for (const page of ordered) {
    if (page - previous > 1) {
      result.push("ellipsis");
    }
    result.push(page);
    previous = page;
  }
  return result;
}

export function storedCasePageSize(reviewerId: string): number {
  try {
    const value = Number(window.localStorage.getItem(`reviewer-case-page-size:${reviewerId}`));
    return CASE_PAGE_SIZES.includes(value as (typeof CASE_PAGE_SIZES)[number])
      ? value
      : DEFAULT_CASE_PAGE_SIZE;
  } catch {
    return DEFAULT_CASE_PAGE_SIZE;
  }
}

export function storeCasePageSize(reviewerId: string, value: number): void {
  try {
    window.localStorage.setItem(`reviewer-case-page-size:${reviewerId}`, String(value));
  } catch {
    // Storage can be unavailable in private/restricted browser contexts; pagination still works.
  }
}

export function formatCaseTitle(item: ReviewerCaseQueueItem) {
  return (
    [item.neutral_citation_display, item.case_title, item.reported_citation_display]
      .filter((part): part is string => Boolean(part && part.trim()))
      .join(" · ") || item.case_title
  );
}

export interface AvailableCaseGroup {
  caseId: string;
  displayTitle: string;
  items: ReviewQueueItem[];
}

export function groupAvailableByCase(items: ReviewQueueItem[]): AvailableCaseGroup[] {
  const groups = new Map<string, AvailableCaseGroup>();
  const order: string[] = [];
  for (const item of items) {
    let group = groups.get(item.case_id);
    if (!group) {
      group = { caseId: item.case_id, displayTitle: item.display_title, items: [] };
      groups.set(item.case_id, group);
      order.push(item.case_id);
    }
    group.items.push(item);
  }
  return order.map((caseId) => groups.get(caseId)!);
}
