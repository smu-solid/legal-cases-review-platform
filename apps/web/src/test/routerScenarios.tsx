import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, vi } from "vitest";
import type {
  AdjudicationDraftResponse,
  CapabilityFlags,
  MeResponse,
  ReviewerGroupingBundle,
} from "../api/types";
import { AppProviders } from "../app/AppProviders";
import { queryClient } from "../app/queryClient";
import { router } from "../app/router";
import { syntheticBundle, syntheticSourceHtml, syntheticSourceMetadata } from "./fixtures/reviewer";

beforeEach(() => {
  queryClient.clear();
});

export const tenantId = "00000000-0000-4000-8000-000000000010";

export const reviewerCampaignId = "00000000-0000-4000-8000-000000000900";

export const reviewerWorkspaceTenantId = "00000000-0000-4000-8000-000000000011";

export const reviewerForbiddenTenantId = "00000000-0000-4000-8000-000000000012";

export const reviewerFailureTenantId = "00000000-0000-4000-8000-000000000013";

export const adminNoCampaignTenantId = "00000000-0000-4000-8000-000000000014";

export function feasibleAvailability(overrides: Record<string, unknown> = {}) {
  return {
    requested_case_count: 30,
    requested_field_scope: [],
    eligible_cases_count: 12,
    source_pool_cases_count: 12,
    case_filter_matching_count: 12,
    projected_campaign_cases_count: 12,
    eligible_review_units_count: 12,
    unavailable_cases_count: 0,
    unavailable_review_units_count: 0,
    fields_fully_exhausted: [],
    fields_partially_available: [],
    cases_available_for_all_selected_fields: 12,
    cases_available_for_some_selected_fields_only: 0,
    feasibility: "feasible_exact",
    infeasible_message: null,
    ...overrides,
  };
}

export function caps(overrides: Partial<CapabilityFlags> = {}): CapabilityFlags {
  return {
    can_administer: false,
    can_review: false,
    can_adjudicate: false,
    can_invite_reviewers: false,
    can_allocate: false,
    can_manage_campaigns: false,
    ...overrides,
  };
}

export const reviewerMe: MeResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "reviewer@local.test",
  display_name: "Reviewer Local",
  subject: "reviewer@local.test",
  status: "active",
  global_roles: [],
  global_capabilities: [],
  active_tenant: tenantId,
  default_landing: "/reviewer",
  capabilities: caps({ can_review: true }),
  session_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  memberships: [
    {
      membership_id: "00000000-0000-4000-8000-000000000002",
      tenant_id: tenantId,
      tenant_key: "local",
      roles: ["reviewer"],
      capabilities: ["review:claim", "review:submit"],
    },
  ],
};

export const adminMe: MeResponse = {
  ...reviewerMe,
  id: "00000000-0000-4000-8000-000000000003",
  email: "admin@local.test",
  display_name: "Admin Local",
  subject: "admin@local.test",
  global_roles: ["super_admin"],
  global_capabilities: ["global:admin"],
  default_landing: "/admin",
  capabilities: caps({
    can_administer: true,
    can_invite_reviewers: true,
    can_allocate: true,
    can_manage_campaigns: true,
  }),
  memberships: [
    {
      ...reviewerMe.memberships[0],
      membership_id: "00000000-0000-4000-8000-000000000004",
      roles: ["super_admin", "campaign_manager"],
      capabilities: ["review:admin"],
    },
  ],
};

export const reviewerWorkspaceMe: MeResponse = {
  ...reviewerMe,
  active_tenant: reviewerWorkspaceTenantId,
  memberships: [
    {
      ...reviewerMe.memberships[0],
      tenant_id: reviewerWorkspaceTenantId,
    },
  ],
};

export const adminNoCampaignMe: MeResponse = {
  ...adminMe,
  active_tenant: adminNoCampaignTenantId,
  memberships: [
    {
      ...adminMe.memberships[0],
      tenant_id: adminNoCampaignTenantId,
    },
  ],
};

export function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

export function textResponse(body: string, contentType = "text/plain") {
  return Promise.resolve(
    new Response(body, {
      status: 200,
      headers: { "content-type": contentType },
    }),
  );
}

export function mockApiSession(me: MeResponse) {
  let signedIn = true;

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return signedIn ? jsonResponse(me) : jsonResponse({ detail: "unauthenticated" }, 401);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      signedIn = false;
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/queue")) {
      return jsonResponse({ items: [], next_cursor: null });
    }

    if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
      return jsonResponse({ items: [], next_cursor: null });
    }

    if (url.includes("/review/campaign-availability") && method === "POST") {
      return jsonResponse(feasibleAvailability());
    }

    if (url.includes("/review/campaign-case-filters/apply") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        case_filter?: { version?: string; all?: unknown[] };
      };
      return jsonResponse({
        normalized_case_filter: body.case_filter ?? { version: "v1", all: [] },
        source_pool_cases_count: 12,
        case_filter_matching_count: 12,
        matching_count_by_source: { sample_a: 6, sample_b: 6 },
        catalog_result_digest: "no_catalog",
        receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        applied_filter_token: "router-test-filter-token",
      });
    }

    if (url.includes("/review/campaign-progress")) {
      return jsonResponse({ items: [] });
    }

    if (url.includes("/review/adjudications")) {
      return jsonResponse([]);
    }

    return jsonResponse({});
  });
}

export function mockAuthenticatedApiSession(me: MeResponse) {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(me);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/queue")) {
      return jsonResponse({ items: [], next_cursor: null });
    }

    if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
      return jsonResponse({ items: [], next_cursor: null });
    }

    if (url.includes("/review/campaign-progress")) {
      return jsonResponse({ items: [] });
    }

    if (url.includes("/review/adjudications")) {
      return jsonResponse([]);
    }

    return jsonResponse({});
  });
}

export function mockDeniedApi(httpStatus: number, code: string) {
  vi.mocked(globalThis.fetch).mockImplementation((input) => {
    const url = String(input);

    if (url.endsWith("/auth/me")) {
      return jsonResponse({ code, detail: "denied", status: httpStatus }, httpStatus);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    return jsonResponse({});
  });
}

export function mockReviewerQueueErrorApi(status: number, queueTenantId: string) {
  const reviewerWithTenant: MeResponse = {
    ...reviewerMe,
    active_tenant: queueTenantId,
    memberships: [
      {
        ...reviewerMe.memberships[0],
        tenant_id: queueTenantId,
      },
    ],
  };

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(reviewerWithTenant);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/queue")) {
      return jsonResponse({ detail: "forbidden" }, status);
    }

    return jsonResponse({});
  });
}

export function mockReviewerQueueWithItems() {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(reviewerMe);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/cases")) {
      return jsonResponse({
        campaign_id: reviewerCampaignId,
        items: [
          {
            case_id: "CASE000000000001",
            case_title: "Assigned case",
            neutral_citation_display: "[2024] SGCA 1",
            reported_citation_display: null,
            campaign_id: reviewerCampaignId,
            anchor_assignment_id: "00000000-0000-4000-8000-000000000801",
            fields_assigned: 2,
            fields_submitted: 0,
            status: "in_progress",
          },
        ],
        schema_version: "reviewer-case-queue/v1",
      });
    }

    if (url.includes("/review/campaigns")) {
      return jsonResponse({
        campaigns: [
          {
            campaign_id: reviewerCampaignId,
            campaign_key: "reviewer-queue-items",
            campaign_name: "Reviewer queue items campaign",
            not_started_count: 1,
            in_progress_count: 1,
            completed_count: 0,
            selected_group_ids: [],
          },
        ],
        schema_version: "reviewer-campaign-queue/v1",
      });
    }

    if (url.includes("/review/queue")) {
      return jsonResponse({
        items: [
          {
            review_unit_id: "00000000-0000-4000-8000-000000000702",
            campaign_id: reviewerCampaignId,
            case_id: "CASE000000000002",
            subject_kind: "case",
            review_kind: "metadata_field",
            display_title: "Claimable review unit",
            display_subtitle: null,
            safe_field_label: "Reporter citation",
            assignment_id: null,
            assignment_status: "available",
          },
        ],
        next_cursor: null,
      });
    }

    return jsonResponse({});
  });
}

export const adjudicationId = "00000000-0000-4000-8000-000000000040";

export function mockAdjudicationQueueApi(me: MeResponse, campaigns: unknown[]) {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(me);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/adjudication-campaigns")) {
      return jsonResponse({
        campaigns,
        next_cursor: null,
        has_more: false,
        schema_version: "adjudication-campaign-queue/v1",
      });
    }

    return jsonResponse({});
  });
}

export function mockAdjudicationQueueErrorApi(me: MeResponse, status: number) {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(me);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/adjudication-campaigns")) {
      return jsonResponse({ detail: "forbidden" }, status);
    }

    return jsonResponse({});
  });
}

export function mockAdjudicationWorkspaceApi(me: MeResponse, remainingAfterSubmit = false) {
  let submitted = false;
  let privateDraft: AdjudicationDraftResponse | null = null;
  const subject = {
    id: "00000000-0000-4000-8000-000000000041",
    subject_kind: "case",
    display_title: "Adjudication subject alpha",
    display_subtitle: null,
    external_subject_id: "ext-adjudication-1",
    primary_source_ref: "source-ref",
    source_snapshot_id: "00000000-0000-4000-8000-000000000042",
    source_version: null,
    attributes: {},
  };

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(me);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.endsWith("/review/adjudications") && method === "GET") {
      return jsonResponse(
        remainingAfterSubmit
          ? [
              {
                display_title: subject.display_title,
                case_id: "case-adjudication-1",
                campaign_id: "00000000-0000-4000-8000-000000000050",
                campaign_name: "Adjudication campaign",
                workspace_adjudication_id: "00000000-0000-4000-8000-000000000044",
                ready_for_me_count: 1,
                awaiting_reviews_count: 0,
                completed_by_me_count: 1,
                total_field_count: 2,
                item_count: 1,
                submitted_review_slots: 6,
                required_review_slots: 6,
                field_progress: [],
                schema_version: "adjudication-case-queue/v2",
              },
            ]
          : [],
      );
    }

    if (url.includes("/review/adjudication-campaigns/") && url.includes("/cases/neighbors")) {
      return jsonResponse({
        previous_open: null,
        next_open: remainingAfterSubmit
          ? {
              case_id: "case-adjudication-2",
              campaign_id: "00000000-0000-4000-8000-000000000050",
              case_title: "Next adjudication case",
              status: "in_progress",
              completion_kind: null,
              status_reason_code: "work_available",
              status_reason: "1 field ready for you",
              progress: {
                total_scoped_fields: 1,
                personal_responsibility_fields: 1,
                completed_responsibility_fields: 0,
                submitted_fields: 0,
                waived_fields: 0,
                not_required_fields: 0,
                pending_fields: 1,
                future_eligible_fields: 0,
              },
              field_progress: [],
              workspace_adjudication_id: "00000000-0000-4000-8000-000000000044",
              workspace_mode: "edit",
            }
          : null,
        schema_version: "adjudication-case-neighbors/v1",
      });
    }

    if (url.includes("/review/adjudication-campaigns/") && url.includes("/cases")) {
      return jsonResponse({
        campaign: {
          campaign_id: "00000000-0000-4000-8000-000000000050",
          campaign_key: "adjudication-campaign",
          campaign_name: "Adjudication campaign",
          waiting_count: 0,
          in_progress_count: 0,
          finished_count: 0,
          not_required_count: 0,
          total_case_count: 0,
        },
        counts: { all: 0, waiting: 0, in_progress: 0, finished: 0, not_required: 0 },
        items: [],
        next_cursor: null,
        has_more: false,
        schema_version: "adjudication-campaign-case-queue/v1",
      });
    }

    if (url.includes("/review/adjudications/") && url.endsWith("/source-render")) {
      return jsonResponse({
        body_url: `${new URL(url, "http://localhost").pathname}/body`,
        anchors_url: `${new URL(url, "http://localhost").pathname}/anchors`,
        render_mode: "sanitized_html",
        artifact_mime_type: "text/html",
      });
    }

    if (url.includes("/review/adjudications/") && url.includes("/source-render/body")) {
      return textResponse("<article><p>Sanitized adjudication document</p></article>", "text/html");
    }

    if (url.includes("/review/adjudications/") && url.endsWith("/source-render/anchors")) {
      return jsonResponse({ render_artifact_id: "artifact-1", anchors: [] });
    }

    if (url.endsWith("/proposal-items"))
      return jsonResponse({
        ready: false,
        required_reviews: 2,
        items: [],
        source_snapshot_id: syntheticBundle.source_render.source_snapshot_id,
        source_version: "a".repeat(64),
      });
    if (url.includes("/review/adjudications/") && url.endsWith("/case-workspace")) {
      return jsonResponse({
        anchor_adjudication_id: adjudicationId,
        schema_version: "adjudication-case-workspace/v1",
        case_id: "case-adjudication-1",
        mode: submitted && !remainingAfterSubmit ? "read_only" : "edit",
        campaign: {
          campaign_id: "00000000-0000-4000-8000-000000000050",
          campaign_key: "adjudication-campaign",
          campaign_name: "Adjudication campaign",
          waiting_count: 0,
          in_progress_count: 2,
          finished_count: 0,
          not_required_count: 0,
          total_case_count: 2,
        },
        case: {
          case_id: "case-adjudication-1",
          campaign_id: "00000000-0000-4000-8000-000000000050",
          case_title: subject.display_title,
          status: submitted && !remainingAfterSubmit ? "finished" : "in_progress",
          completion_kind: submitted && !remainingAfterSubmit ? "completed" : null,
          status_reason_code:
            submitted && !remainingAfterSubmit ? "completed_by_me" : "work_available",
          status_reason:
            submitted && !remainingAfterSubmit
              ? "All adjudication required from you is complete"
              : "2 fields ready for you",
          progress: {
            total_scoped_fields: 2,
            personal_responsibility_fields: 2,
            completed_responsibility_fields: submitted ? 1 : 0,
            submitted_fields: submitted ? 1 : 0,
            waived_fields: 0,
            not_required_fields: 0,
            pending_fields: submitted ? (remainingAfterSubmit ? 1 : 0) : 2,
            future_eligible_fields: 0,
          },
          field_progress: [],
          workspace_adjudication_id: adjudicationId,
          workspace_mode: submitted && !remainingAfterSubmit ? "read_only" : "edit",
        },
        case_header: {
          subject_id: subject.id,
          subject_kind: "case",
          case_title: subject.display_title,
          case_identifier_display: subject.external_subject_id,
          neutral_citation_display: "[2017] SGHC 12",
          reported_citation_display: "[2017] 4 REP 3",
          source_system: "sample_a",
          campaign_name: "Adjudication campaign",
        },
        source_render: {
          source_snapshot_id: subject.source_snapshot_id,
          render_mode: "safe_text",
          content: "[2017] SGHC 12\nReported [2017] 4 REP 3",
          truncated: false,
          omitted_anchor_count: 0,
          anchors: [
            {
              anchor_id: "unit:neutral-citation",
              review_unit_id: "00000000-0000-4000-8000-000000000043",
              item_id: "item-neutral-citation",
              group_id: "group-citations",
              char_start: 0,
              char_end: 14,
              scroll_hint: "center",
              label: "Neutral citation",
            },
            {
              anchor_id: "unit:reported-citation",
              review_unit_id: "00000000-0000-4000-8000-000000000045",
              item_id: "item-reported-citation",
              group_id: "group-citations",
              char_start: 24,
              char_end: 38,
              scroll_hint: "center",
              label: "Reported citation",
            },
          ],
        },
        field_groups: [
          {
            group_id: "group-citations",
            group_kind: "atomic",
            group_label: "Citations",
            description: "Citation fields",
            order: 1,
            items: [
              {
                adjudication_id: adjudicationId,
                item_id: "item-neutral-citation",
                item_kind: "field",
                item_label: "Neutral citation",
                extracted_value_display: "[2017] SGHC 12",
                review_kind: "metadata_field",
                review_unit_id: "00000000-0000-4000-8000-000000000043",
                required_reviews: 3,
                submitted_reviews: 3,
                source_anchor_id: "unit:neutral-citation",
                source_anchor_unavailable_reason: null,
                evidence_window_ids: [],
                evidence_windows: [],
                assessment_targets: [
                  {
                    id: "00000000-0000-4000-8000-00000000004a",
                    label: "A",
                  },
                  {
                    id: "00000000-0000-4000-8000-00000000004b",
                    label: "B",
                  },
                ],
                submissions: [
                  {
                    submission_id: "00000000-0000-4000-8000-000000000051",
                    pseudonym: "Reviewer Owl",
                    reviewer: {
                      display_name: "Aisha Rahman",
                      email: "aisha@example.test",
                    },
                    value_correct: true,
                    provenance_correct: false,
                    corrected_value: null,
                    corrected_value_display: null,
                    corrected_provenance_spans: [
                      {
                        evidence_window_id: "00000000-0000-4000-8000-000000000061",
                        char_start: 0,
                        char_end: 14,
                        note: null,
                      },
                    ],
                    evidence_ids: ["00000000-0000-4000-8000-000000000061"],
                    failure_reason: "evidence_wrong_location",
                    comment: "Citation matches the source.",
                    submitted_at: new Date().toISOString(),
                  },
                  {
                    submission_id: "00000000-0000-4000-8000-000000000052",
                    pseudonym: "Reviewer Fox",
                    reviewer: {
                      display_name: null,
                      email: "fallback-reviewer@example.test",
                    },
                    value_correct: true,
                    provenance_correct: false,
                    corrected_value: null,
                    corrected_value_display: null,
                    corrected_provenance_spans: [
                      {
                        evidence_window_id: "00000000-0000-4000-8000-000000000063",
                        char_start: 7,
                        char_end: 14,
                        note: null,
                      },
                    ],
                    evidence_ids: [],
                    failure_reason: "evidence_wrong_location",
                    comment: null,
                    submitted_at: new Date().toISOString(),
                  },
                  {
                    submission_id: "00000000-0000-4000-8000-000000000053",
                    pseudonym: "Reviewer Newt",
                    reviewer: {
                      display_name: "Ben Tan",
                      email: "ben@example.test",
                    },
                    value_correct: false,
                    provenance_correct: true,
                    corrected_value: "[2017] SGHC 13",
                    corrected_value_display: "[2017] SGHC 13",
                    corrected_provenance_spans: [],
                    evidence_ids: [],
                    failure_reason: "value_incorrect",
                    comment: "Suggested a correction.",
                    submitted_at: new Date().toISOString(),
                  },
                ],
                draft: submitted ? null : privateDraft,
                participation_status: submitted ? "submitted" : "pending",
                submitted_decision: null,
              },
              {
                adjudication_id: "00000000-0000-4000-8000-000000000044",
                item_id: "item-reported-citation",
                item_kind: "field",
                item_label: "Reported citation",
                extracted_value_display: "[2017] 4 REP 3",
                review_kind: "metadata_field",
                review_unit_id: "00000000-0000-4000-8000-000000000045",
                required_reviews: 3,
                submitted_reviews: 3,
                source_anchor_id: "unit:reported-citation",
                source_anchor_unavailable_reason: null,
                evidence_window_ids: [],
                evidence_windows: [],
                assessment_targets: [],
                submissions: [
                  {
                    submission_id: "00000000-0000-4000-8000-000000000054",
                    pseudonym: "Reviewer Hawk",
                    reviewer: {
                      display_name: "Chloe Lim",
                      email: "chloe@example.test",
                    },
                    value_correct: true,
                    provenance_correct: true,
                    corrected_value: null,
                    corrected_value_display: null,
                    corrected_provenance_spans: [],
                    evidence_ids: [],
                    failure_reason: null,
                    comment: null,
                    submitted_at: new Date().toISOString(),
                  },
                ],
                draft: null,
                participation_status: remainingAfterSubmit ? "pending" : "submitted",
                submitted_decision: {
                  decision_id: "00000000-0000-4000-8000-000000000098",
                  adjudication_id: "00000000-0000-4000-8000-000000000044",
                  review_unit_id: "00000000-0000-4000-8000-000000000045",
                  outcome: "all_equivalent_supported",
                  preferred_candidate_id: null,
                  preferred_submission_id: null,
                  corrected_value: null,
                  corrected_value_display: null,
                  corrected_provenance_spans: [
                    {
                      evidence_window_id: "00000000-0000-4000-8000-000000000062",
                      char_start: 24,
                      char_end: 38,
                      note: null,
                    },
                  ],
                  assessments: [],
                  reviewer_assessments: [],
                  comment: "Final read-only note",
                  evidence_ids: [],
                  status: "submitted",
                  resolved: false,
                  decided_at: new Date().toISOString(),
                  replayed: false,
                  schema_version: "adjudication-decision/v2",
                },
              },
            ],
          },
        ],
      });
    }

    if (url.includes("/review/adjudications/") && url.endsWith("/draft") && method === "PUT") {
      const decision = JSON.parse(String(init?.body));
      privateDraft = {
        adjudication_id: adjudicationId,
        decision,
        saved_at: new Date().toISOString(),
        replayed: false,
        schema_version: "adjudication-draft/v2",
      };
      return jsonResponse(privateDraft);
    }

    if (url.includes("/review/adjudications/") && url.endsWith("/submit") && method === "POST") {
      submitted = true;
      return jsonResponse({ decision_id: "00000000-0000-4000-8000-000000000099" }, 201);
    }

    if (url.endsWith(`/review/adjudications/${adjudicationId}/bundle`)) {
      return jsonResponse({
        adjudication_id: adjudicationId,
        schema_version: "adjudication-bundle/v1",
        review_kind: "value_provenance",
        review_subject: subject,
        candidates: [
          {
            id: "00000000-0000-4000-8000-00000000004a",
            label: "A",
            rationale: "Candidate A rationale",
            supporting_quote: null,
            value: "[2017] SGHC 12",
            verdict: "correct",
          },
          {
            id: "00000000-0000-4000-8000-00000000004b",
            label: "B",
            rationale: "Candidate B rationale",
            supporting_quote: null,
            value: "[2017] SGHC 13",
            verdict: "incorrect",
          },
        ],
        evidence_windows: [],
        submissions: [],
      });
    }

    return jsonResponse({});
  });
}

export function mockReviewerStagingApi() {
  const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
  const reviewUnitId = syntheticBundle.field_groups[0].items[0].review_unit_id;

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(reviewerWorkspaceMe);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/review/campaigns")) {
      return jsonResponse({
        campaigns: [
          {
            campaign_id: reviewerCampaignId,
            campaign_key: "reviewer-staging",
            campaign_name: "Reviewer staging campaign",
            not_started_count: 0,
            in_progress_count: 1,
            completed_count: 0,
            selected_group_ids: [],
          },
        ],
        schema_version: "reviewer-campaign-queue/v1",
      });
    }

    if (url.includes("/review/queue")) {
      return jsonResponse({
        items: [
          {
            review_unit_id: reviewUnitId,
            assignment_id: assignmentId,
            campaign_id: reviewerCampaignId,
            case_id: "CASE-STAGING-0001",
            subject_kind: "case",
            review_kind: "value_provenance",
            display_title: syntheticBundle.case_header.case_title,
            display_subtitle: syntheticBundle.case_header.neutral_citation_display,
            safe_field_label: "Grouped case fields",
            assignment_status: "assigned",
          },
        ],
        has_more: false,
        next_cursor: null,
      });
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
      return jsonResponse(syntheticBundle);
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
      return jsonResponse(syntheticSourceMetadata);
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/source-render/body`)) {
      return textResponse(syntheticSourceHtml, "text/html");
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/source-render/anchors`)) {
      return jsonResponse({
        render_artifact_id: syntheticSourceMetadata.render_artifact_id,
        schema_version: "source-render-anchor-map/v1",
        anchors: [
          {
            anchor_id: "anchor-neutral-citation",
            char_start: syntheticSourceHtml.indexOf("[2017] SGHC 12"),
            char_end: syntheticSourceHtml.indexOf("[2017] SGHC 12") + "[2017] SGHC 12".length,
            label: "Neutral citation",
          },
          {
            anchor_id: "anchor-date",
            char_start: syntheticSourceHtml.indexOf("14 February 2017"),
            char_end: syntheticSourceHtml.indexOf("14 February 2017") + "14 February 2017".length,
            label: "Decision date",
          },
          {
            anchor_id: "anchor-coram",
            char_start: syntheticSourceHtml.indexOf("Justice A. Rahman"),
            char_end: syntheticSourceHtml.indexOf("Justice A. Rahman") + "Justice A. Rahman".length,
            label: "Coram",
          },
        ],
      });
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/answer/draft`) && method === "PUT") {
      return jsonResponse({
        status: "draft",
        lock_version: 2,
      });
    }

    if (url.endsWith(`/review/assignments/${assignmentId}/answer/submit`) && method === "POST") {
      return jsonResponse({
        status: "submitted",
        lock_version: 3,
      });
    }

    return jsonResponse({});
  });
}

export function mockAdminStagingApi(previewOverride?: Record<string, unknown>) {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(adminMe);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.endsWith("/reviewers") && method === "POST") {
      return jsonResponse(
        {
          user_id: "00000000-0000-4000-8000-000000000103",
          membership_id: "00000000-0000-4000-8000-000000000203",
          user_status: "pending",
          membership_status: "pending",
          invitation_email: "sent",
        },
        201,
      );
    }

    if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
      return jsonResponse({
        items: [
          {
            user_id: "00000000-0000-4000-8000-000000000101",
            membership_id: "00000000-0000-4000-8000-000000000201",
            display_name: "Reviewer One",
            user_status: "active",
            membership_status: "active",
            roster_status: "active",
            roles: ["reviewer"],
            eligible: true,
            total_assignments: 7,
            submitted_count: 3,
            claimed_count: 2,
            released_count: 1,
          },
          {
            user_id: "00000000-0000-4000-8000-000000000102",
            membership_id: "00000000-0000-4000-8000-000000000202",
            display_name: "Reviewer Two",
            user_status: "active",
            membership_status: "active",
            roster_status: "active",
            roles: ["reviewer"],
            eligible: true,
            total_assignments: 5,
            submitted_count: 1,
            claimed_count: 1,
            released_count: 0,
          },
          {
            user_id: "00000000-0000-4000-8000-000000000103",
            membership_id: "00000000-0000-4000-8000-000000000203",
            display_name: "Reviewer Pending",
            user_status: "pending",
            membership_status: "pending",
            roster_status: "pending",
            roles: ["reviewer"],
            eligible: false,
          },
        ],
        next_cursor: null,
      });
    }

    if (url.includes("/review/campaign-availability") && method === "POST") {
      return jsonResponse(feasibleAvailability());
    }

    if (url.includes("/review/campaign-progress")) {
      return jsonResponse({
        tenant_id: tenantId,
        items: [
          {
            campaign_id: "00000000-0000-4000-8000-000000000301",
            campaign_name: "Local staging campaign",
            campaign_key: "local-staging",
            campaign_status: "draft",
            cases_total: 3,
            total_units: 12,
            unit_status_counts: { pending: 12, in_review: 0, in_adjudication: 0, resolved: 0 },
            total_assignments: 0,
            assignment_status_counts: { claimed: 0, submitted: 0, released: 0 },
            reviewers_total: 2,
            case_reviewer_slots_total: 6,
            case_reviewer_completions: 0,
            cases_fully_complete_count: 0,
          },
        ],
      });
    }

    if (url.includes("/review/reviewer-workload")) {
      return jsonResponse({
        tenant_id: tenantId,
        campaign_id: "00000000-0000-4000-8000-000000000301",
        items: [],
      });
    }

    if (url.includes("/review/scope-catalog")) {
      return jsonResponse({
        tenant_id: tenantId,
        contract_version: "campaign-scope-catalog/v1",
        groups: [
          {
            group_id: "citation",
            group_label: "Citation",
            group_kind: "atomic",
            order: 1,
            description: "Neutral and reporter citations.",
          },
          {
            group_id: "judge",
            group_label: "Judge",
            group_kind: "non_atomic",
            order: 2,
            description: null,
          },
        ],
        review_kinds: ["metadata_field"],
      });
    }

    if (url.endsWith("/allocation-runs/preview") && method === "POST") {
      return jsonResponse(
        previewOverride ?? {
          feasibility: {
            status: "feasible",
            errors: [],
            warnings: [],
            computed_totals: {},
            suggested_adjustments: [],
          },
          pairwise_overlap_matrix: {},
          reviewer_workloads: [
            {
              reviewer_id: "00000000-0000-4000-8000-000000000101",
              planned_assignment_count: 10,
              unique_assignment_count: 10,
              pairwise_overlap_count: 2,
              global_overlap_count: 2,
            },
          ],
          subject_coverage: null,
          pool_digest: "pool",
          source_snapshot_digest: "snapshot",
          allocation_policy_version: "reviewer-allocation/v1",
          planner_version: "planner",
        },
      );
    }

    if (url.endsWith("/allocation-runs") && method === "POST") {
      return jsonResponse(
        {
          run_id: "00000000-0000-4000-8000-000000000401",
          campaign_id: "00000000-0000-4000-8000-000000000301",
          status: "planned",
          feasibility_status: "feasible",
          allocation_policy_version: "reviewer-allocation/v1",
          planner_version: "planner",
          source_snapshot_digest: "snapshot",
          pool_digest: "pool",
          planned_assignment_count: 20,
          distinct_subject_count: 10,
          reviewer_count: 2,
          created_at: new Date().toISOString(),
          published_at: null,
          lock_version: 1,
        },
        201,
      );
    }

    if (url.endsWith("/publish") && method === "POST") {
      return jsonResponse(
        {
          run_id: "00000000-0000-4000-8000-000000000401",
          status: "published",
          published_assignment_count: 20,
          created_assignment_count: 20,
          published_at: new Date().toISOString(),
        },
        201,
      );
    }

    return jsonResponse({});
  });
}

export function mockAdminWithoutCampaigns() {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/me")) {
      return jsonResponse(adminNoCampaignMe);
    }

    if (url.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }

    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }

    if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
      return jsonResponse({
        items: [
          {
            user_id: "00000000-0000-4000-8000-000000000101",
            membership_id: "00000000-0000-4000-8000-000000000201",
            display_name: "Reviewer One",
            user_status: "active",
            membership_status: "active",
            roster_status: "active",
            roles: ["reviewer"],
            eligible: true,
            total_assignments: 7,
            submitted_count: 3,
            claimed_count: 2,
            released_count: 1,
          },
          {
            user_id: "00000000-0000-4000-8000-000000000102",
            membership_id: "00000000-0000-4000-8000-000000000202",
            display_name: "Reviewer Two",
            user_status: "active",
            membership_status: "active",
            roster_status: "active",
            roles: ["reviewer"],
            eligible: true,
            total_assignments: 5,
            submitted_count: 1,
            claimed_count: 1,
            released_count: 0,
          },
        ],
        next_cursor: null,
      });
    }

    if (url.includes("/review/campaign-availability") && method === "POST") {
      return jsonResponse(feasibleAvailability());
    }

    if (url.includes("/pool-cases") && method === "POST") {
      return jsonResponse({
        campaign_id: "00000000-0000-4000-8000-000000000402",
        availability: feasibleAvailability(),
        materialized_cases: 12,
        materialized_units: 12,
        total_units: 12,
        not_ready_for_publish: false,
      });
    }

    if (url.endsWith("/review/campaigns") && method === "POST") {
      return jsonResponse(
        {
          campaign_id: "00000000-0000-4000-8000-000000000402",
          campaign_key: "authored-key",
          campaign_name: "Authored campaign",
          status: "draft",
          total_units: 12,
          availability: feasibleAvailability(),
          not_ready_for_publish: false,
        },
        201,
      );
    }

    if (url.includes("/review/campaign-progress")) {
      return jsonResponse({ tenant_id: tenantId, items: [] });
    }

    return jsonResponse({});
  });
}

export function renderAt(path: string) {
  const testRouter = createMemoryRouter(router.routes, {
    initialEntries: [path],
  });

  render(
    <AppProviders>
      <RouterProvider router={testRouter} />
    </AppProviders>,
  );
}

export async function enterAppAs(me: MeResponse) {
  mockApiSession(me);
  const user = userEvent.setup();
  renderAt("/");

  return user;
}

export function expectNoProtectedSampleContent() {
  expect(screen.queryByText(/public prosecutor v tan wei ming/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/synthetic source/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/immutable source artifact/i)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: /your assigned campaigns/i }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: /campaign and reviewer operations/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /adjudication queue/i })).not.toBeInTheDocument();
}

export function mockAllFieldsSubmitted(caseSubmitCalls: string[]) {
  const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
  const submittedItem = {
    ...syntheticBundle.field_groups[0].items[0],
    status: "submitted" as const,
    answer_summary: {
      state: "submitted" as const,
      value_correct: true,
      provenance_correct: true,
      corrected_value_display: null,
      comment: null,
      failure_reason: null,
      corrected_provenance_spans: [],
    },
  };
  const bundle: ReviewerGroupingBundle = {
    ...syntheticBundle,
    field_groups: [{ ...syntheticBundle.field_groups[0], items: [submittedItem] }],
    progress: {
      total_items: 1,
      completed_items: 1,
      remaining_items: 0,
      group_progress: [{ group_id: "case_metadata", completed_count: 1, item_count: 1 }],
    },
  };
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
    if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
    if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
      return jsonResponse(bundle);
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
      return jsonResponse({ detail: "not_found" }, 404);
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/case-submit`) && method === "POST") {
      caseSubmitCalls.push(url);
      return jsonResponse({
        case_id: "CASE-STAGING-0001",
        campaign_id: reviewerCampaignId,
        submitted_at: "2026-07-10T00:00:00Z",
        replayed: false,
      });
    }
    return jsonResponse({});
  });
  return assignmentId;
}

export function mockReadyCaseWithNav({
  caseSubmitCalls,
  caseSubmitStatus = 201,
  nextCase,
}: {
  caseSubmitCalls: string[];
  caseSubmitStatus?: number;
  nextCase?: { assignmentId: string; caseTitle: string; bundle: ReviewerGroupingBundle };
}) {
  const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
  const submittedItem = {
    ...syntheticBundle.field_groups[0].items[0],
    status: "submitted" as const,
    answer_summary: {
      state: "submitted" as const,
      value_correct: true,
      provenance_correct: true,
      corrected_value_display: null,
      comment: null,
      failure_reason: null,
      corrected_provenance_spans: [],
    },
  };
  const bundle: ReviewerGroupingBundle = {
    ...syntheticBundle,
    field_groups: [{ ...syntheticBundle.field_groups[0], items: [submittedItem] }],
    progress: {
      total_items: 1,
      completed_items: 1,
      remaining_items: 0,
      group_progress: [{ group_id: "case_metadata", completed_count: 1, item_count: 1 }],
    },
  };
  const caseQueueItems = [
    {
      case_id: "CASE-STAGING-0001",
      case_title: bundle.case_header.case_title,
      neutral_citation_display: bundle.case_header.neutral_citation_display,
      reported_citation_display: null,
      campaign_id: reviewerCampaignId,
      anchor_assignment_id: assignmentId,
      fields_assigned: 1,
      fields_submitted: 1,
      status: "in_progress" as const,
    },
    ...(nextCase
      ? [
          {
            case_id: "CASE-STAGING-0002",
            case_title: nextCase.caseTitle,
            neutral_citation_display: null,
            reported_citation_display: null,
            campaign_id: reviewerCampaignId,
            anchor_assignment_id: nextCase.assignmentId,
            fields_assigned: 1,
            fields_submitted: 0,
            status: "not_started" as const,
          },
        ]
      : []),
  ];

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
    if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
      return jsonResponse(bundle);
    }
    if (nextCase && url.endsWith(`/review/assignments/${nextCase.assignmentId}/grouped-bundle`)) {
      return jsonResponse(nextCase.bundle);
    }
    if (url.includes("/review/assignments/") && url.endsWith("/source-render")) {
      return jsonResponse({ detail: "not_found" }, 404);
    }
    if (url.includes("/cases") && url.includes(reviewerCampaignId)) {
      return jsonResponse({
        campaign_id: reviewerCampaignId,
        items: caseQueueItems,
        has_more: false,
        next_cursor: null,
        schema_version: "reviewer-case-queue/v1",
      });
    }
    if (url.includes("/review/campaigns") && !url.includes("/cases")) {
      return jsonResponse({
        campaigns: [
          {
            campaign_id: reviewerCampaignId,
            campaign_key: "reviewer-staging",
            campaign_name: "Reviewer staging campaign",
            not_started_count: nextCase ? 1 : 0,
            in_progress_count: 1,
            completed_count: 0,
            selected_group_ids: [],
          },
        ],
        schema_version: "reviewer-campaign-queue/v1",
      });
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/case-submit`) && method === "POST") {
      caseSubmitCalls.push(url);
      if (caseSubmitStatus !== 201) {
        return jsonResponse(
          { code: "case_submit_failed", detail: "The case could not be submitted." },
          caseSubmitStatus,
        );
      }
      return jsonResponse({
        case_id: "CASE-STAGING-0001",
        campaign_id: reviewerCampaignId,
        submitted_at: "2026-07-10T00:00:00Z",
        replayed: false,
      });
    }
    if (url.includes("/review/queue")) {
      return jsonResponse({ items: [], has_more: false, next_cursor: null });
    }
    return jsonResponse({});
  });

  return assignmentId;
}

export function mockWorkspaceWrites(
  assignmentId: string,
  onWrite: (kind: "draft" | "submit", init: RequestInit | undefined) => Promise<Response>,
) {
  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
    if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
    if (url.endsWith("/auth/logout") && method === "POST") {
      return jsonResponse({ status: "logged_out" });
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
      return jsonResponse(syntheticBundle);
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
      return jsonResponse({ detail: "not_found" }, 404);
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/answer/draft`) && method === "PUT") {
      return onWrite("draft", init);
    }
    if (url.endsWith(`/review/assignments/${assignmentId}/answer/submit`) && method === "POST") {
      return onWrite("submit", init);
    }
    return jsonResponse({});
  });
}

export async function answerCurrentFieldYes(user: ReturnType<typeof userEvent.setup>) {
  const [valueYes, provenanceYes] = screen.getAllByRole("button", { name: /^yes$/i });
  await user.click(valueYes);
  await user.click(provenanceYes);
}
