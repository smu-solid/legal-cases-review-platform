import { apiDownload, apiRequest, makeIdempotencyKey } from "../client";
import type {
  CampaignAllocationSummaryResponse,
  CampaignAvailabilityRequest,
  CampaignAvailabilityResponse,
  CampaignCaseFilterApplyRequest,
  CampaignCaseFilterApplyResponse,
  CampaignCaseFilterCorrectionRequest,
  CampaignCaseFilterCorrectionResponse,
  CampaignCaseFilterExportRequest,
  CampaignCaseIdApplyRequest,
  CampaignCaseIdApplyResponse,
  CampaignCaseProgressPage,
  CampaignDeleteResponse,
  CampaignDetailResponse,
  CampaignEditRequest,
  CampaignProgressResponse,
  CampaignScopeCatalogResponse,
  CreateCampaignRequest,
  CreateCampaignResponse,
  LoadPoolCasesRequest,
  LoadPoolCasesResponse,
  SyntheticImportRequest,
  SyntheticImportResponse,
} from "../types";

export function createCampaign(
  tenantId: string,
  body: CreateCampaignRequest,
  csrfToken: string | null,
) {
  return apiRequest<CreateCampaignResponse>(`/admin/tenants/${tenantId}/review/campaigns`, {
    method: "POST",
    body,
    csrfToken,
    idempotencyKey: makeIdempotencyKey(`create-campaign-${body.campaign_key}`),
  });
}

export function previewCampaignAvailability(
  tenantId: string,
  body: CampaignAvailabilityRequest,
  signal?: AbortSignal,
) {
  // The preview scans the whole pool server-side, so a superseded request (form state moved on)
  // is aborted instead of left running: React Query hands the signal in, fetch cancels it.
  return apiRequest<CampaignAvailabilityResponse>(
    `/admin/tenants/${tenantId}/review/campaign-availability`,
    { method: "POST", body, signal },
  );
}

export function applyCampaignCaseFilters(tenantId: string, body: CampaignCaseFilterApplyRequest) {
  return apiRequest<CampaignCaseFilterApplyResponse>(
    `/admin/tenants/${tenantId}/review/campaign-case-filters/apply`,
    { method: "POST", body },
  );
}

export function applyCampaignCaseIds(tenantId: string, body: CampaignCaseIdApplyRequest) {
  return apiRequest<CampaignCaseIdApplyResponse>(
    `/admin/tenants/${tenantId}/review/campaign-case-ids/apply`,
    { method: "POST", body },
  );
}

export function suggestCampaignCaseFilterCorrections(
  tenantId: string,
  body: CampaignCaseFilterCorrectionRequest,
) {
  return apiRequest<CampaignCaseFilterCorrectionResponse>(
    `/admin/tenants/${tenantId}/review/campaign-case-filters/corrections`,
    { method: "POST", body },
  );
}

export function exportCampaignCaseFilterIds(
  tenantId: string,
  body: CampaignCaseFilterExportRequest,
  csrfToken: string | null,
) {
  return apiDownload(
    `/admin/tenants/${tenantId}/review/campaign-case-filters/export`,
    body,
    csrfToken,
  );
}

export function loadPoolCases(
  tenantId: string,
  campaignId: string,
  body: LoadPoolCasesRequest,
  csrfToken: string | null,
) {
  return apiRequest<LoadPoolCasesResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/pool-cases`,
    {
      method: "POST",
      body,
      csrfToken,
      idempotencyKey: makeIdempotencyKey(
        `load-pool-cases-${campaignId}-${body.requested_case_count}`,
      ),
    },
  );
}

export function importSyntheticReviewCampaign(
  tenantId: string,
  body: SyntheticImportRequest,
  csrfToken: string | null,
) {
  return apiRequest<SyntheticImportResponse>(`/admin/tenants/${tenantId}/review/import-synthetic`, {
    method: "POST",
    body,
    csrfToken,
    idempotencyKey: makeIdempotencyKey(`import-synthetic-${body.campaign_key}`),
  });
}

export function getCampaignProgress(tenantId: string) {
  return apiRequest<CampaignProgressResponse>(
    `/admin/tenants/${tenantId}/review/campaign-progress`,
  );
}

export function getCampaignScopeCatalog(tenantId: string) {
  return apiRequest<CampaignScopeCatalogResponse>(
    `/admin/tenants/${tenantId}/review/scope-catalog`,
  );
}

export function getCampaign(tenantId: string, campaignId: string) {
  return apiRequest<CampaignDetailResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}`,
  );
}

export function editCampaign(
  tenantId: string,
  campaignId: string,
  body: CampaignEditRequest,
  csrfToken: string | null,
) {
  return apiRequest<CampaignDetailResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}`,
    { method: "PATCH", body, csrfToken },
  );
}

export function deleteCampaign(
  tenantId: string,
  campaignId: string,
  confirm: boolean,
  csrfToken: string | null,
) {
  return apiRequest<CampaignDeleteResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}?confirm=${confirm ? "true" : "false"}`,
    { method: "DELETE", csrfToken },
  );
}

export function completeCampaign(tenantId: string, campaignId: string, csrfToken: string | null) {
  return apiRequest<CampaignDetailResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/complete`,
    {
      method: "POST",
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`complete-campaign-${campaignId}`),
    },
  );
}

export function getCampaignAllocationSummary(tenantId: string, campaignId: string) {
  return apiRequest<CampaignAllocationSummaryResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/allocation-summary?include_plan=false`,
  );
}

export function listCampaignCases(
  tenantId: string,
  campaignId: string,
  params: { limit?: number; cursor?: string | null } = {},
) {
  const query = new URLSearchParams();
  if (params.limit) {
    query.set("limit", String(params.limit));
  }
  if (params.cursor) {
    query.set("cursor", params.cursor);
  }
  const queryString = query.toString();
  return apiRequest<CampaignCaseProgressPage>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/cases${queryString ? `?${queryString}` : ""}`,
  );
}
