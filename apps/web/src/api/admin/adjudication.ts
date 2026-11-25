import { apiRequest, makeIdempotencyKey } from "../client";
import type {
  AdjudicationBundle,
  AdjudicationCampaignCaseQueuePage,
  AdjudicationCampaignQueuePage,
  AdjudicationCaseNeighbors,
  AdjudicationCaseWorkspace,
  AdjudicationDecisionInput,
  AdjudicationDecisionResponse,
  AdjudicationDraftInput,
  AdjudicationDraftResponse,
  AdjudicationGroupedBundle,
  AdjudicationSummary,
  SourceRenderAnchorMap,
  SourceRenderArtifactMetadata,
} from "../types";

export function listAdjudications(tenantId: string) {
  return apiRequest<AdjudicationSummary[]>(`/tenants/${tenantId}/review/adjudications`);
}

export function listAdjudicationCampaigns(tenantId: string, cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiRequest<AdjudicationCampaignQueuePage>(
    `/tenants/${tenantId}/review/adjudication-campaigns${query}`,
  );
}

export function listAdjudicationCampaignCases(
  tenantId: string,
  campaignId: string,
  status: "all" | "waiting" | "in_progress" | "finished" | "not_required" = "all",
  cursor?: string,
) {
  const params = new URLSearchParams({ status });
  if (cursor) params.set("cursor", cursor);
  return apiRequest<AdjudicationCampaignCaseQueuePage>(
    `/tenants/${tenantId}/review/adjudication-campaigns/${campaignId}/cases?${params}`,
  );
}

export function getAdjudicationCaseNeighbors(
  tenantId: string,
  campaignId: string,
  anchorAdjudicationId: string,
) {
  const params = new URLSearchParams({ anchor_adjudication_id: anchorAdjudicationId });
  return apiRequest<AdjudicationCaseNeighbors>(
    `/tenants/${tenantId}/review/adjudication-campaigns/${campaignId}/cases/neighbors?${params}`,
  );
}

export function getAdjudicationCaseWorkspace(tenantId: string, adjudicationId: string) {
  return apiRequest<AdjudicationCaseWorkspace>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/case-workspace`,
  );
}

export function getAdjudicationSourceRenderMetadata(tenantId: string, adjudicationId: string) {
  return apiRequest<SourceRenderArtifactMetadata>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/source-render`,
  );
}

export function getAdjudicationSourceRenderBody(
  tenantId: string,
  adjudicationId: string,
  reviewUnitId: string,
) {
  const params = new URLSearchParams({ review_unit_id: reviewUnitId });
  return apiRequest<string>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/source-render/body?${params}`,
  );
}

export function getAdjudicationSourceRenderAnchors(tenantId: string, adjudicationId: string) {
  return apiRequest<SourceRenderAnchorMap>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/source-render/anchors`,
  );
}

export function getAdjudicationGroupedBundle(tenantId: string, adjudicationId: string) {
  return apiRequest<AdjudicationGroupedBundle>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/grouped-bundle`,
  );
}

export function getAdjudicationBundle(tenantId: string, adjudicationId: string) {
  return apiRequest<AdjudicationBundle>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/bundle`,
  );
}

export function submitAdjudicationDecision(
  tenantId: string,
  adjudicationId: string,
  body: AdjudicationDecisionInput,
  csrfToken: string | null,
) {
  return apiRequest<AdjudicationDecisionResponse>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/submit`,
    {
      method: "POST",
      body,
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`submit-adjudication-${adjudicationId}`),
    },
  );
}

export function saveAdjudicationDraft(
  tenantId: string,
  adjudicationId: string,
  body: AdjudicationDraftInput,
  csrfToken: string | null,
) {
  return apiRequest<AdjudicationDraftResponse>(
    `/tenants/${tenantId}/review/adjudications/${adjudicationId}/draft`,
    {
      method: "PUT",
      body,
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`save-adjudication-draft-${adjudicationId}`),
    },
  );
}
