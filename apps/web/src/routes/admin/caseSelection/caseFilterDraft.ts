import type { CampaignCaseFilter } from "../../../api/types";

export type DraftFilterRow = { id: string; field: FilterField; value: string };

export const emptyFilter: CampaignCaseFilter = { version: "v1", all: [] };

export function yearValueText(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (!value || typeof value !== "object" || !("ranges" in value)) return "";
  const ranges = (value as { ranges?: Array<{ start: number; end: number }> }).ranges ?? [];
  return ranges
    .map((item) => (item.start === item.end ? String(item.start) : `${item.start}-${item.end}`))
    .join(", ");
}

export function rowsFromFilter(filter: CampaignCaseFilter | null | undefined): DraftFilterRow[] {
  return (filter?.all ?? []).map((clause) => ({
    id: crypto.randomUUID(),
    field: clause.field_id,
    value: clause.field_id === "case_subject" ? String(clause.value) : yearValueText(clause.value),
  }));
}

export type FilterField = "case_subject" | "judgment_year";
