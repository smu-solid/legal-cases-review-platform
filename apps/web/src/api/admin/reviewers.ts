import { apiRequest, makeIdempotencyKey } from "../client";
import type {
  CampaignReviewersResponse,
  ReviewerInviteRequest,
  ReviewerInviteResponse,
  ReviewerWorkloadResponse,
  TenantReviewerRosterPage,
} from "../types";

export function listTenantReviewers(tenantId: string) {
  return apiRequest<TenantReviewerRosterPage>(`/admin/tenants/${tenantId}/reviewers`);
}

export function addCampaignReviewer(
  tenantId: string,
  campaignId: string,
  reviewerId: string,
  csrfToken: string | null,
) {
  return apiRequest<CampaignReviewersResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/reviewers`,
    {
      method: "POST",
      body: { reviewer_id: reviewerId },
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`add-campaign-reviewer-${campaignId}-${reviewerId}`),
    },
  );
}

export function removeCampaignReviewer(
  tenantId: string,
  campaignId: string,
  reviewerId: string,
  csrfToken: string | null,
) {
  return apiRequest<CampaignReviewersResponse>(
    `/admin/tenants/${tenantId}/review/campaigns/${campaignId}/reviewers/${reviewerId}`,
    { method: "DELETE", csrfToken },
  );
}

export function getReviewerWorkload(tenantId: string, campaignId: string) {
  return apiRequest<ReviewerWorkloadResponse>(
    `/admin/tenants/${tenantId}/review/reviewer-workload?campaign_id=${campaignId}`,
  );
}

export function inviteReviewerToRoster(
  tenantId: string,
  body: ReviewerInviteRequest,
  csrfToken: string | null,
) {
  return apiRequest<ReviewerInviteResponse>(`/admin/tenants/${tenantId}/reviewers`, {
    method: "POST",
    body,
    csrfToken,
  });
}
