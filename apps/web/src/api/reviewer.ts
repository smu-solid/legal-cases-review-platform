import { apiRequest, makeIdempotencyKey } from "./client";
import type {
  CaseSubmissionResponse,
  ClaimRequest,
  ClaimResponse,
  ReviewItemAnswerInput,
  ReviewItemAnswerResponse,
  ReviewQueuePage,
  ReviewerCampaignQueuePage,
  ReviewerCaseQueuePage,
  ReviewerGroupingBundle,
  SourceRenderAnchorMap,
  SourceRenderArtifactMetadata,
} from "./types";

export interface ReviewQueueFilter {
  campaignId?: string;
  assignmentStatus?: "available" | "assigned" | "completed";
  cursor?: string | null;
  limit?: number;
}

export function listReviewQueue(tenantId: string, filter: ReviewQueueFilter = {}) {
  const params = new URLSearchParams({ subject_kind: "case" });
  if (filter.campaignId) {
    params.set("campaign_id", filter.campaignId);
  }
  if (filter.assignmentStatus) {
    params.set("assignment_status", filter.assignmentStatus);
  }
  if (filter.cursor) {
    params.set("cursor", filter.cursor);
  }
  if (filter.limit) {
    params.set("limit", String(filter.limit));
  }
  return apiRequest<ReviewQueuePage>(`/tenants/${tenantId}/review/queue?${params.toString()}`);
}

// One card per campaign the reviewer is assigned to, with own-work-only not-started/in-progress/
// completed counts. Backing list for the reviewer landing page; the flat, paginated per-unit queue
// lives at listReviewQueue(tenantId, { campaignId }).
function pageQuery(opts?: { cursor?: string | null; limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.cursor) params.set("cursor", opts.cursor);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// Keyset-paginated (see queue.py): pass the previous page's next_cursor to load the next page.
export function listReviewerCampaignQueue(
  tenantId: string,
  opts?: { cursor?: string | null; limit?: number },
) {
  return apiRequest<ReviewerCampaignQueuePage>(
    `/tenants/${tenantId}/review/campaigns${pageQuery(opts)}`,
  );
}

// Case-grouped list of the reviewer's own claimed/submitted work in one campaign -- one row per
// distinct case, never one per field/review-unit. Backs the reviewer campaign->cases queue page;
// the still-open, not-yet-claimed pool stays the flat per-field listReviewQueue above.
// Keyset-paginated by (first-claimed-at, case id); pass next_cursor to load the next page.
export function listReviewerCaseQueue(
  tenantId: string,
  campaignId: string,
  opts?: { cursor?: string | null; limit?: number },
) {
  return apiRequest<ReviewerCaseQueuePage>(
    `/tenants/${tenantId}/review/campaigns/${campaignId}/cases${pageQuery(opts)}`,
  );
}

export function claimReviewUnit(tenantId: string, request: ClaimRequest, csrfToken: string | null) {
  return apiRequest<ClaimResponse>(`/tenants/${tenantId}/review/claim`, {
    method: "POST",
    body: request,
    csrfToken,
    idempotencyKey: makeIdempotencyKey("claim"),
  });
}

export function getGroupedReviewBundle(tenantId: string, assignmentId: string) {
  return apiRequest<ReviewerGroupingBundle>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/grouped-bundle`,
  );
}

// Reviewer-safe metadata for the derived source-render artifact. Absent (HTTP 404) when no
// sanitized-HTML artifact has been emitted for the assignment; callers then fall back to the
// grouped bundle's inline `safe_text` render.
export function getSourceRenderMetadata(tenantId: string, assignmentId: string) {
  return apiRequest<SourceRenderArtifactMetadata>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/source-render`,
  );
}

// The sanitized `text/html` artifact body, delivered as a string for a sandboxed iframe. The
// backend guarantees it is nh3-sanitized (no scripts, handlers, or off-origin resources); the UI
// still renders it inside a locked-down `sandbox` iframe as defence in depth.
export function getSourceRenderBody(tenantId: string, assignmentId: string) {
  return apiRequest<string>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/source-render/body`,
  );
}

// Offset-only map for the rendered artifact representation. These coordinates are intentionally
// kept separate from grouped-bundle safe-text anchors because they address different source bodies.
export function getSourceRenderAnchors(tenantId: string, assignmentId: string) {
  return apiRequest<SourceRenderAnchorMap>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/source-render/anchors`,
  );
}

export function saveAnswerDraft(
  tenantId: string,
  assignmentId: string,
  lockVersion: number,
  body: ReviewItemAnswerInput,
  csrfToken: string | null,
) {
  return apiRequest<ReviewItemAnswerResponse>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/answer/draft`,
    {
      method: "PUT",
      body,
      csrfToken,
      ifMatch: lockVersion,
      idempotencyKey: makeIdempotencyKey(`draft-${assignmentId}`),
    },
  );
}

export function submitAnswer(
  tenantId: string,
  assignmentId: string,
  lockVersion: number,
  body: ReviewItemAnswerInput,
  csrfToken: string | null,
) {
  return apiRequest<ReviewItemAnswerResponse>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/answer/submit`,
    {
      method: "POST",
      body,
      csrfToken,
      ifMatch: lockVersion,
      idempotencyKey: makeIdempotencyKey(`submit-${assignmentId}`),
    },
  );
}

export function submitReviewerCase(
  tenantId: string,
  assignmentId: string,
  csrfToken: string | null,
) {
  return apiRequest<CaseSubmissionResponse>(
    `/tenants/${tenantId}/review/assignments/${assignmentId}/case-submit`,
    {
      method: "POST",
      csrfToken,
      idempotencyKey: makeIdempotencyKey(`case-submit-${assignmentId}`),
    },
  );
}
