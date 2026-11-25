import type {
  CampaignCaseFilter,
  CampaignCaseFilterApplyResponse,
  CampaignCaseIdApplyResponse,
  CampaignCaseIdSelection,
} from "../../../api/types";
export interface AppliedCaseIdState {
  caseIdSelection: CampaignCaseIdSelection | null;
  fileName: string | null;
  result: CampaignCaseIdApplyResponse | null;
  ready: boolean;
  sourceSignature: string;
}
export interface AppliedCaseFilterState {
  caseFilter: CampaignCaseFilter;
  result: CampaignCaseFilterApplyResponse | null;
  draftChanged: boolean;
  receiptExpired: boolean;
  ready: boolean;
  sourceSignature: string;
}
