import { useMutation } from "@tanstack/react-query";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { applyCampaignCaseIds } from "../../../api/admin";
import type { CampaignCaseIdApplyResponse, CampaignCaseIdSelection } from "../../../api/types";
import { MAX_FILE_BYTES, parseCaseIds, readFileText } from "./caseIdFiles";
import type { AppliedCaseIdState } from "./types";

export function useCampaignCaseIdUpload({
  sourceFamilies,
  initialSelection,
  initialFileName,
  tenantId,
  enabled,
  onStateChange,
}: {
  sourceFamilies: string[];
  initialSelection: { case_ids: string[]; version: "v1" } | null | undefined;
  initialFileName: string | null | undefined;
  tenantId: string;
  enabled: boolean;
  onStateChange: (state: AppliedCaseIdState) => void;
}) {
  const sourceSignature = JSON.stringify(sourceFamilies);
  const previousSourceSignature = useRef(sourceSignature);
  const currentSourceSignature = useRef(sourceSignature);
  currentSourceSignature.current = sourceSignature;
  const [selection, setSelection] = useState<CampaignCaseIdSelection | null>(
    initialSelection ?? null,
  );
  const [result, setResult] = useState<CampaignCaseIdApplyResponse | null>(null);
  const [fileName, setFileName] = useState<string | null>(initialFileName ?? null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [receiptExpired, setReceiptExpired] = useState(false);
  const [appliedSourceSignature, setAppliedSourceSignature] = useState("");
  const [copied, setCopied] = useState(false);
  const [initialApplyPending, setInitialApplyPending] = useState(Boolean(initialSelection));
  const [fileInputKey, setFileInputKey] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const uploadOperation = useRef(0);

  const applyMutation = useMutation({
    mutationFn: (request: {
      caseIdSelection: CampaignCaseIdSelection;
      sourceFamilies: string[];
      sourceSignature: string;
    }) =>
      applyCampaignCaseIds(tenantId, {
        source_families: request.sourceFamilies,
        case_id_selection: request.caseIdSelection,
      }),
    onSuccess: (response, request) => {
      if (currentSourceSignature.current !== request.sourceSignature) return;
      setSelection(response.normalized_case_id_selection);
      setResult(response);
      setReceiptExpired(false);
      setAppliedSourceSignature(request.sourceSignature);
    },
  });

  useEffect(() => {
    if (previousSourceSignature.current === sourceSignature) return;
    previousSourceSignature.current = sourceSignature;
    uploadOperation.current += 1;
    setSelection(null);
    setResult(null);
    setFileName(null);
    setValidationError(null);
    setReceiptExpired(false);
    setAppliedSourceSignature("");
    setCopied(false);
    setInitialApplyPending(false);
    setFileInputKey((current) => current + 1);
    setDragActive(false);
    dragDepth.current = 0;
  }, [sourceSignature]);

  useEffect(() => {
    if (!enabled || !initialApplyPending || !selection || applyMutation.isPending) return;
    setInitialApplyPending(false);
    applyMutation.mutate({ caseIdSelection: selection, sourceFamilies, sourceSignature });
  }, [applyMutation, enabled, initialApplyPending, selection, sourceFamilies, sourceSignature]);

  useEffect(() => {
    if (!result) return;
    const delay = new Date(result.receipt_expires_at).getTime() - Date.now();
    if (!Number.isFinite(delay)) return;
    if (delay <= 0) {
      setReceiptExpired(true);
      return;
    }
    const timer = window.setTimeout(() => setReceiptExpired(true), delay);
    return () => window.clearTimeout(timer);
  }, [result]);

  const ready =
    Boolean(selection && result) && appliedSourceSignature === sourceSignature && !receiptExpired;
  useEffect(() => {
    onStateChange({ caseIdSelection: selection, fileName, result, ready, sourceSignature });
  }, [fileName, onStateChange, ready, result, selection, sourceSignature]);

  function clearAppliedUpload() {
    setSelection(null);
    setResult(null);
    setReceiptExpired(false);
    setAppliedSourceSignature("");
    setCopied(false);
    setFileName(null);
  }

  async function acceptFile(nextFile: File | null) {
    const operation = uploadOperation.current + 1;
    uploadOperation.current = operation;
    setCopied(false);
    setValidationError(null);
    setFileInputKey((current) => current + 1);
    if (!nextFile) {
      clearAppliedUpload();
      return;
    }
    if (!nextFile.name.toLowerCase().endsWith(".txt")) {
      setValidationError("Choose a .txt file with one case ID per line.");
      return;
    }
    if (nextFile.size > MAX_FILE_BYTES) {
      setValidationError("The case-ID file must not exceed 1 MB.");
      return;
    }
    try {
      const parsed = parseCaseIds(await readFileText(nextFile));
      if (
        uploadOperation.current !== operation ||
        currentSourceSignature.current !== sourceSignature
      ) {
        return;
      }
      setFileName(nextFile.name);
      setSelection(parsed);
      setResult(null);
      setReceiptExpired(false);
      setAppliedSourceSignature("");
      applyMutation.mutate({ caseIdSelection: parsed, sourceFamilies, sourceSignature });
    } catch (error) {
      if (uploadOperation.current !== operation) return;
      setValidationError(error instanceof Error ? error.message : "The file could not be read.");
    }
  }

  function acceptSingleFile(incomingFiles: File[]) {
    if (incomingFiles.length !== 1) {
      setValidationError("Choose exactly one .txt file.");
      return;
    }
    void acceptFile(incomingFiles[0]);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.target.files ?? []);
    if (selectedFiles.length > 0) acceptSingleFile(selectedFiles);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    if (!enabled) return;
    acceptSingleFile(Array.from(event.dataTransfer.files));
  }

  function removeFile() {
    void acceptFile(null);
  }

  async function copyUnmatchedIds() {
    if (!result?.unmatched_case_ids.length) return;
    try {
      await navigator.clipboard.writeText(result.unmatched_case_ids.join("\n"));
      setCopied(true);
    } catch {
      setValidationError("Unmatched case IDs could not be copied to the clipboard.");
    }
  }
  return {
    selection,
    result,
    fileName,
    validationError,
    receiptExpired,
    copied,
    fileInputKey,
    dragActive,
    setDragActive,
    dragDepth,
    applyMutation,
    handleFileChange,
    handleDrop,
    removeFile,
    copyUnmatchedIds,
  };
}
