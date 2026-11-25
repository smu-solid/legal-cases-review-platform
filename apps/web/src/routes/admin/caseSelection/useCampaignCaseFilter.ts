import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  applyCampaignCaseFilters,
  exportCampaignCaseFilterIds,
  suggestCampaignCaseFilterCorrections,
} from "../../../api/admin";
import type { CampaignCaseFilter, CampaignCaseFilterApplyResponse } from "../../../api/types";
import { parseJudgmentYearValue } from "../campaignCaseFilterYears";
import { DraftFilterRow, emptyFilter, rowsFromFilter } from "./caseFilterDraft";
import type { AppliedCaseFilterState } from "./types";

export function useCampaignCaseFilter({
  initialFilter,
  sourceFamilies,
  tenantId,
  enabled,
  onStateChange,
  csrfToken,
}: {
  initialFilter: CampaignCaseFilter | null | undefined;
  sourceFamilies: string[];
  tenantId: string;
  enabled: boolean;
  onStateChange: (state: AppliedCaseFilterState) => void;
  csrfToken: string | null;
}) {
  const [filterRows, setFilterRows] = useState<DraftFilterRow[]>(() =>
    rowsFromFilter(initialFilter),
  );
  const [appliedFilter, setAppliedFilter] = useState<CampaignCaseFilter>(emptyFilter);
  const [appliedResult, setAppliedResult] = useState<CampaignCaseFilterApplyResponse | null>(null);
  const [appliedSignature, setAppliedSignature] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [receiptExpired, setReceiptExpired] = useState(false);
  const [dismissedSuggestionQuery, setDismissedSuggestionQuery] = useState("");
  const [debouncedSubjectQuery, setDebouncedSubjectQuery] = useState("");
  const [initialApplyPending, setInitialApplyPending] = useState(
    () => (initialFilter?.all?.length ?? 0) > 0,
  );

  const draftSignature = useMemo(
    () =>
      JSON.stringify({
        source_families: sourceFamilies,
        rows: filterRows.map(({ field, value }) => ({ field, value })),
      }),
    [filterRows, sourceFamilies],
  );
  const draftChanged = draftSignature !== appliedSignature;
  const emptyDraft = filterRows.length === 0;
  const ready = emptyDraft || (Boolean(appliedResult) && !draftChanged && !receiptExpired);
  const sourceSignature = JSON.stringify(sourceFamilies);

  function buildFilter(): CampaignCaseFilter | null {
    const all: CampaignCaseFilter["all"] = [];
    try {
      for (const row of filterRows) {
        const value = row.value.trim();
        if (!value) throw new Error("Complete or remove every filter row before applying.");
        if (row.field === "case_subject") {
          all.push({ field_id: "case_subject", operator: "contains_ci", value });
        } else {
          all.push({
            field_id: "judgment_year",
            operator: "in_ranges",
            value: parseJudgmentYearValue(value),
          });
        }
      }
      setValidationError(null);
      return { version: "v1", all };
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : "Check the filter values.");
      return null;
    }
  }

  const applyMutation = useMutation({
    mutationFn: (request: { caseFilter: CampaignCaseFilter; signature: string }) =>
      applyCampaignCaseFilters(tenantId, {
        source_families: sourceFamilies,
        case_filter: request.caseFilter,
      }),
    onSuccess: (response, request) => {
      setAppliedFilter(response.normalized_case_filter ?? request.caseFilter);
      setAppliedResult(response);
      setAppliedSignature(request.signature);
      setReceiptExpired(false);
    },
  });

  function applyFilters() {
    const caseFilter = buildFilter();
    if (caseFilter) applyMutation.mutate({ caseFilter, signature: draftSignature });
  }

  // A retained non-empty selector was already explicitly applied when it was saved; refresh its
  // short-lived receipt when this editor is enabled. A new/empty form needs no Apply handshake.
  useEffect(() => {
    if (!enabled || !initialApplyPending || applyMutation.isPending || !initialFilter) return;
    setInitialApplyPending(false);
    applyMutation.mutate({ caseFilter: initialFilter, signature: draftSignature });
  }, [applyMutation, draftSignature, enabled, initialApplyPending, initialFilter]);

  useEffect(() => {
    if (!emptyDraft) return;
    setAppliedFilter(emptyFilter);
    setAppliedResult(null);
    setAppliedSignature(draftSignature);
    setReceiptExpired(false);
  }, [draftSignature, emptyDraft]);

  useEffect(() => {
    if (!appliedResult) return;
    const delay = new Date(appliedResult.receipt_expires_at).getTime() - Date.now();
    if (!Number.isFinite(delay)) return;
    if (delay <= 0) {
      setReceiptExpired(true);
      return;
    }
    const timer = window.setTimeout(() => setReceiptExpired(true), delay);
    return () => window.clearTimeout(timer);
  }, [appliedResult]);

  useEffect(() => {
    onStateChange({
      caseFilter: emptyDraft ? emptyFilter : appliedFilter,
      result: emptyDraft ? null : appliedResult,
      draftChanged: emptyDraft ? false : draftChanged,
      receiptExpired: emptyDraft ? false : receiptExpired,
      ready,
      sourceSignature,
    });
  }, [
    appliedFilter,
    appliedResult,
    draftChanged,
    emptyDraft,
    onStateChange,
    ready,
    receiptExpired,
    sourceSignature,
  ]);

  const subjectValue = filterRows.find((row) => row.field === "case_subject")?.value.trim() ?? "";
  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSubjectQuery(subjectValue.length >= 3 ? subjectValue : ""),
      400,
    );
    return () => window.clearTimeout(timer);
  }, [subjectValue]);

  const correctionQuery = useQuery({
    queryKey: ["campaign-case-filter-correction", tenantId, sourceFamilies, debouncedSubjectQuery],
    queryFn: () =>
      suggestCampaignCaseFilterCorrections(tenantId, {
        field_id: "case_subject",
        query: debouncedSubjectQuery,
        source_families: sourceFamilies,
        limit: 5,
      }),
    enabled:
      enabled &&
      debouncedSubjectQuery.length >= 3 &&
      debouncedSubjectQuery !== dismissedSuggestionQuery,
    retry: false,
  });

  const exportMutation = useMutation({
    mutationFn: () =>
      exportCampaignCaseFilterIds(
        tenantId,
        {
          source_families: sourceFamilies,
          case_filter: emptyDraft ? emptyFilter : appliedFilter,
          applied_filter_token: emptyDraft ? undefined : appliedResult?.applied_filter_token,
        },
        csrfToken,
      ),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    },
  });

  return {
    filterRows,
    setFilterRows,
    appliedResult,
    validationError,
    receiptExpired,
    setDismissedSuggestionQuery,
    debouncedSubjectQuery,
    draftChanged,
    emptyDraft,
    ready,
    applyMutation,
    applyFilters,
    correctionQuery,
    exportMutation,
  };
}
