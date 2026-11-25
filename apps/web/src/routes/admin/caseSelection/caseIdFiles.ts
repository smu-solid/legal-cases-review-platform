const MAX_CASE_ID_LENGTH = 200;
import type { CampaignCaseIdSelection } from "../../../api/types";

export const MAX_CASE_IDS = 10_000;

export function parseCaseIds(contents: string): CampaignCaseIdSelection {
  const caseIds: string[] = [];
  const seen = new Set<string>();
  for (const [index, line] of contents.split(/\r\n|\n|\r/).entries()) {
    const caseId = (index === 0 ? line.replace(/^\ufeff/, "") : line).trim();
    if (!caseId || seen.has(caseId)) continue;
    if (caseId.length > MAX_CASE_ID_LENGTH) {
      throw new Error(`Case IDs must not exceed ${MAX_CASE_ID_LENGTH} characters.`);
    }
    seen.add(caseId);
    caseIds.push(caseId);
  }
  if (caseIds.length === 0) throw new Error("The text file does not contain any case IDs.");
  if (caseIds.length > MAX_CASE_IDS) {
    throw new Error(
      `The uploaded file may contain at most ${MAX_CASE_IDS.toLocaleString()} unique case IDs.`,
    );
  }
  return { version: "v1", case_ids: caseIds };
}

export function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsText(file, "UTF-8");
  });
}

export const MAX_FILE_BYTES = 1_000_000;
