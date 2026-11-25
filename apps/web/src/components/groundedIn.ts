import type { components } from "../api/generated/openapi";

export type EvidenceWindow = components["schemas"]["EvidenceWindowResponse"];
export type GroundedIn = components["schemas"]["GroundedIn"];

export const OTHER_DOCUMENT_MESSAGE = "Evidence is recorded in another source document.";
export const UNLOCATABLE_MESSAGE = "No locatable provenance for this field.";

/** How the source pane explains an evidence window that cannot be highlighted in this document. */
export type EvidenceLocationNotice = {
  kind: "other_document" | "unlocatable";
  message: string;
  /** Present only for other-document evidence: where that evidence actually lives. */
  recordedIn?: string;
};

/**
 * A reviewer-safe name for the document an evidence window was taken from: the member's citation
 * when available, or a shortened document hash.
 */
export function describeGroundedIn(groundedIn: GroundedIn | null | undefined): string | null {
  if (!groundedIn) return null;
  if (groundedIn.citation) return groundedIn.citation;
  const hash = groundedIn.source_sha256 ? groundedIn.source_sha256.slice(0, 12) : "";
  return hash ? `Document ${hash}` : null;
}

/**
 * The notice for an item whose anchor is unavailable. ``other_document`` (the server's honest
 * classification) never reads as "no locatable provenance": the evidence exists and is intact, it
 * simply lives in another document of the same family, which is named when the windows carry it.
 * Every other unavailable state keeps the existing message.
 */
export function evidenceLocationNotice(
  reason: string | null | undefined,
  windows: readonly EvidenceWindow[] | null | undefined,
): EvidenceLocationNotice {
  if (reason === "other_document") {
    const elsewhere = (windows ?? []).find((window) => window.anchor_status === "other_document");
    const recordedIn = describeGroundedIn(elsewhere?.grounded_in ?? null);
    return {
      kind: "other_document",
      message: OTHER_DOCUMENT_MESSAGE,
      ...(recordedIn ? { recordedIn } : {}),
    };
  }
  return { kind: "unlocatable", message: UNLOCATABLE_MESSAGE };
}
