import { apiRequest, makeIdempotencyKey } from "../client";
import type {
  AllocationPolicyInput,
  AllocationPreviewResponse,
  AllocationPublishResponse,
  AllocationRunPage,
  IncrementalPolicyInput,
  IncrementalPreviewResponse,
  IncrementalPublishResponse,
  IncrementalRunResponse,
} from "../types";

export function previewAllocationRun(
  tenantId: string,
  campaignId: string,
  body: AllocationPolicyInput,
  csrfToken: string | null,
) {
  return apiRequest<AllocationPreviewResponse>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs/preview`,
    {
      method: "POST",
      body,
      csrfToken,
    },
  );
}

export function listAllocationRuns(tenantId: string, campaignId: string) {
  return apiRequest<AllocationRunPage>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs?limit=100`,
  );
}

export function previewIncrementalAllocation(
  tenantId: string,
  campaignId: string,
  body: IncrementalPolicyInput,
  csrfToken: string | null,
) {
  return apiRequest<IncrementalPreviewResponse>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs/incremental-preview`,
    { method: "POST", body, csrfToken },
  );
}

export async function publishIncrementalAllocation(
  tenantId: string,
  campaignId: string,
  body: IncrementalPolicyInput,
  csrfToken: string | null,
) {
  const run = await apiRequest<IncrementalRunResponse>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs/incremental`,
    {
      method: "POST",
      body,
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`incremental-plan-${campaignId}`),
    },
  );
  return apiRequest<IncrementalPublishResponse>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs/${run.run_id}/publish-incremental`,
    {
      method: "POST",
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`incremental-publish-${run.run_id}`),
    },
  );
}

export function publishAllocationPlan(
  tenantId: string,
  campaignId: string,
  body: AllocationPolicyInput,
  csrfToken: string | null,
) {
  return apiRequest<AllocationPublishResponse>(
    `/admin/tenants/${tenantId}/campaigns/${campaignId}/allocation-runs/publish`,
    {
      method: "POST",
      body,
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`publish-plan-${campaignId}`),
    },
  );
}
