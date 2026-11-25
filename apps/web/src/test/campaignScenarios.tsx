import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import type { CapabilityFlags, MeResponse } from "../api/types";
import { AppProviders } from "../app/AppProviders";
import { router } from "../app/router";

export const reviewerAId = "00000000-0000-4000-8000-000000000101";

export const reviewerBId = "00000000-0000-4000-8000-000000000102";

export let idSeq = 0;

export function freshIds() {
  idSeq += 1;
  const suffix = String(idSeq).padStart(4, "0");
  return {
    tenantId: `00000000-0000-4000-8000-0000002${suffix}`,
    campaignId: `00000000-0000-4000-8000-0000003${suffix}`,
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

export function adminMeFor(tenantId: string): MeResponse {
  return {
    id: "00000000-0000-4000-8000-000000000003",
    email: "admin@local.test",
    display_name: "Admin Local",
    subject: "admin@local.test",
    status: "active",
    global_roles: ["super_admin"],
    global_capabilities: ["global:admin"],
    active_tenant: tenantId,
    default_landing: "/admin",
    capabilities: caps({
      can_administer: true,
      can_invite_reviewers: true,
      can_allocate: true,
      can_manage_campaigns: true,
    }),
    session_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    memberships: [
      {
        membership_id: "00000000-0000-4000-8000-000000000004",
        tenant_id: tenantId,
        tenant_key: "local",
        roles: ["super_admin", "campaign_manager"],
        capabilities: ["review:admin"],
      },
    ],
  };
}

export function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

export function baseCampaign(campaignId: string, overrides: Partial<Record<string, unknown>> = {}) {
  return {
    campaign_id: campaignId,
    campaign_key: "local-staging",
    campaign_name: "Local staging campaign",
    status: "draft",
    review_scope: null,
    reviews_per_case: 2,
    selected_reviewer_ids: [] as string[],
    total_units: 12,
    synthesize_missing_values: false,
    case_filter: { version: "v1", all: [] },
    completed: false,
    schema_version: "campaign-detail/v1",
    ...overrides,
  };
}

export function baseAllocationSummary(
  campaignId: string,
  overrides: Partial<Record<string, unknown>> = {},
) {
  return {
    campaign_id: campaignId,
    selected_cases: 12,
    reviews_per_case: 2,
    selected_reviewers: 0,
    total_assignments: 24,
    // Deliberately NOT a multiple of total_assignments' shape: 60 units x 2 reviews = 120, versus
    // 12 cases x 2 = 24. The two granularities must stay visibly distinct on the page.
    review_units: 60,
    total_unit_assignments: 120,
    estimated_assignments_per_reviewer: 0,
    feasible: false,
    infeasible_reason: "no_selected_reviewers",
    infeasible_message: "No active reviewers are selected yet. Add at least 2 before allocating.",
    schema_version: "campaign-allocation-summary/v1",
    assignment_plan: [] as unknown[],
    ...overrides,
  };
}

export function baseRoster() {
  return {
    items: [
      {
        user_id: reviewerAId,
        membership_id: "00000000-0000-4000-8000-000000000201",
        display_name: "Reviewer One",
        user_status: "active",
        membership_status: "active",
        roster_status: "active",
        roles: ["reviewer"],
        eligible: true,
        total_assignments: 0,
        submitted_count: 0,
        claimed_count: 0,
        released_count: 0,
      },
      {
        user_id: reviewerBId,
        membership_id: "00000000-0000-4000-8000-000000000202",
        display_name: "Reviewer Two",
        user_status: "active",
        membership_status: "active",
        roster_status: "active",
        roles: ["reviewer"],
        eligible: true,
        total_assignments: 0,
        submitted_count: 0,
        claimed_count: 0,
        released_count: 0,
      },
    ],
    next_cursor: null,
  };
}

export function mockCampaignDetailApi(
  tenantId: string,
  campaignId: string,
  options: {
    campaign?: Record<string, unknown>;
    allocationSummary?: Record<string, unknown>;
    cases?: unknown[];
    editHandler?: (body: Record<string, unknown>) => Promise<Response>;
    deleteHandler?: (confirm: string | null) => Promise<Response>;
    completeHandler?: () => Promise<Response>;
    reviewerHandler?: (method: string) => Promise<Response>;
    roster?: { items: unknown[]; next_cursor: null };
    progress?: Record<string, unknown>;
    allocationPreview?: Record<string, unknown>;
    availability?: Record<string, unknown>;
    workload?: unknown[];
    afterPoolCases?: {
      campaign?: Record<string, unknown>;
      allocationSummary?: Record<string, unknown>;
      cases?: unknown[];
      progress?: Record<string, unknown>;
      availability?: Record<string, unknown>;
    };
  } = {},
) {
  let campaign = options.campaign ?? baseCampaign(campaignId);
  let allocationSummary = options.allocationSummary ?? baseAllocationSummary(campaignId);
  let cases = options.cases ?? [];
  let progress = options.progress;
  let availability = options.availability;
  const roster = options.roster ?? baseRoster();
  // Mutable so the default complete-then-refetch flow reflects the mutation the way the real
  // backend would (marking completed persists, so the next GET returns completed=true too).
  let completedOverride = Boolean(campaign.completed);

  vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    const method = init?.method ?? "GET";

    if (path.endsWith("/auth/me")) {
      return jsonResponse(adminMeFor(tenantId));
    }
    if (path.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}`) && method === "GET") {
      return jsonResponse({ ...campaign, completed: completedOverride });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}`) && method === "PATCH") {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      if (options.editHandler) return options.editHandler(body);
      campaign = { ...campaign, ...body };
      return jsonResponse(campaign);
    }
    if (path.endsWith(`/review/campaigns/${campaignId}`) && method === "DELETE") {
      return options.deleteHandler
        ? options.deleteHandler(url.searchParams.get("confirm"))
        : jsonResponse({
            campaign_id: campaignId,
            status: "closed",
            schema_version: "campaign-delete/v1",
          });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}/complete`) && method === "POST") {
      if (options.completeHandler) {
        return options.completeHandler();
      }
      completedOverride = true;
      return jsonResponse({ ...campaign, status: "published", completed: true });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}/allocation-summary`)) {
      return jsonResponse(allocationSummary);
    }
    if (path.endsWith("/review/campaign-case-filters/apply") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        case_filter?: { version?: string; all?: unknown[] };
      };
      const count = body.case_filter?.all?.length ? 3 : 5;
      return jsonResponse({
        normalized_case_filter: body.case_filter ?? { version: "v1", all: [] },
        source_pool_cases_count: 5,
        case_filter_matching_count: count,
        matching_count_by_source: { sample_a: count, sample_b: count },
        unidentifiable_pool_units_count: 0,
        identity_unavailable_cases_count: 0,
        identity_conflict_cases_count: 0,
        catalog_result_digest: "test-digest",
        receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        applied_filter_token: "test-filter-token",
        schema_version: "campaign-case-filter-apply/v1",
      });
    }
    if (path.endsWith("/review/campaign-case-ids/apply") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        case_id_selection: { case_ids: string[] };
      };
      const unmatched = body.case_id_selection.case_ids.filter((caseId) => caseId === "MISSING");
      const matchingCount = body.case_id_selection.case_ids.length - unmatched.length;
      return jsonResponse({
        normalized_case_id_selection: body.case_id_selection,
        source_pool_cases_count: 5,
        uploaded_unique_count: body.case_id_selection.case_ids.length,
        case_id_matching_count: matchingCount,
        matching_count_by_source: { sample_a: matchingCount, sample_b: 0 },
        unmatched_case_ids: unmatched,
        receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        applied_case_id_token: "test-case-id-token",
        schema_version: "campaign-case-id-apply/v1",
      });
    }
    if (path.endsWith("/review/campaign-case-filters/corrections") && method === "POST") {
      return jsonResponse({
        typed_value: "",
        suggestions: [],
        schema_version: "campaign-case-filter-corrections/v1",
      });
    }
    if (path.endsWith("/review/campaign-availability") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        case_filter?: { all?: unknown[] };
      };
      const defaultCount = body.case_filter?.all?.length ? 3 : 5;
      return jsonResponse({
        requested_case_count: 12,
        requested_field_scope: [],
        eligible_cases_count: defaultCount,
        source_pool_cases_count: 5,
        case_filter_matching_count: defaultCount,
        projected_campaign_cases_count: defaultCount,
        eligible_review_units_count: defaultCount,
        unavailable_cases_count: 0,
        unavailable_review_units_count: 0,
        fields_fully_exhausted: [],
        fields_partially_available: [],
        cases_available_for_all_selected_fields: 5,
        cases_available_for_some_selected_fields_only: 0,
        feasibility: "feasible_exact",
        infeasible_message: null,
        schema_version: "campaign-availability/v1",
        ...availability,
      });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}/pool-cases`) && method === "POST") {
      if (options.afterPoolCases) {
        campaign = { ...campaign, ...options.afterPoolCases.campaign };
        allocationSummary = {
          ...allocationSummary,
          ...options.afterPoolCases.allocationSummary,
        };
        cases = options.afterPoolCases.cases ?? cases;
        progress = { ...progress, ...options.afterPoolCases.progress };
        availability = { ...availability, ...options.afterPoolCases.availability };
      }
      return jsonResponse({
        campaign_id: campaignId,
        availability: {
          requested_case_count: 12,
          requested_field_scope: [],
          eligible_cases_count: 5,
          eligible_review_units_count: 5,
          unavailable_cases_count: 0,
          unavailable_review_units_count: 0,
          fields_fully_exhausted: [],
          fields_partially_available: [],
          cases_available_for_all_selected_fields: 5,
          cases_available_for_some_selected_fields_only: 0,
          feasibility: "feasible_exact",
          infeasible_message: null,
          schema_version: "campaign-availability/v1",
        },
        materialized_cases: 5,
        materialized_units: 5,
        total_units: 17,
        not_ready_for_publish: false,
        schema_version: "load-pool-cases/v1",
      });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}/cases`)) {
      return jsonResponse({
        campaign_id: campaignId,
        items: cases,
        next_cursor: null,
        has_more: false,
        schema_version: "campaign-case-progress/v1",
      });
    }
    if (path.endsWith(`/review/campaigns/${campaignId}/reviewers`) && method === "POST") {
      return options.reviewerHandler
        ? options.reviewerHandler("POST")
        : jsonResponse({
            campaign_id: campaignId,
            selected_reviewer_ids: [reviewerAId],
            schema_version: "campaign-reviewers/v1",
          });
    }
    if (path.includes(`/review/campaigns/${campaignId}/reviewers/`) && method === "DELETE") {
      return options.reviewerHandler
        ? options.reviewerHandler("DELETE")
        : jsonResponse({
            campaign_id: campaignId,
            selected_reviewer_ids: [],
            schema_version: "campaign-reviewers/v1",
          });
    }
    if (path.includes("/admin/tenants/") && path.endsWith("/reviewers")) {
      return jsonResponse(roster);
    }
    if (path.includes("/review/campaign-progress")) {
      return jsonResponse({
        tenant_id: tenantId,
        items: [
          {
            campaign_id: campaignId,
            campaign_name: campaign.campaign_name,
            campaign_key: campaign.campaign_key,
            campaign_status: campaign.status,
            cases_total: 12,
            reviewers_total: (campaign.selected_reviewer_ids as string[]).length,
            total_units: 12,
            unit_status_counts: { pending: 12, in_review: 0, in_adjudication: 0, resolved: 0 },
            total_assignments: 0,
            assignment_status_counts: { claimed: 0, submitted: 0, released: 0 },
            case_reviewer_slots_total: 0,
            case_reviewer_completions: 0,
            cases_fully_complete_count: 0,
            ...progress,
          },
        ],
      });
    }
    if (path.includes("/review/reviewer-workload")) {
      return jsonResponse({
        tenant_id: tenantId,
        campaign_id: campaignId,
        items: options.workload ?? [],
        schema_version: "reviewer-workload/v1",
      });
    }
    if (path.includes("/review/scope-catalog")) {
      return jsonResponse({
        tenant_id: tenantId,
        contract_version: "campaign-scope-catalog/v1",
        groups: [],
        review_kinds: [],
      });
    }
    if (path.endsWith("/allocation-runs/preview") && method === "POST") {
      return jsonResponse({
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
            reviewer_id: reviewerAId,
            planned_assignment_count: 12,
            unique_assignment_count: 12,
            pairwise_overlap_count: 0,
            global_overlap_count: 0,
          },
          {
            reviewer_id: reviewerBId,
            planned_assignment_count: 12,
            unique_assignment_count: 12,
            pairwise_overlap_count: 0,
            global_overlap_count: 0,
          },
        ],
        subject_coverage: null,
        planned_assignment_counts: { cases: 24, review_units: 120 },
        pool_digest: "pool",
        source_snapshot_digest: "snapshot",
        allocation_policy_version: "reviewer-allocation/v1",
        planner_version: "planner",
        ...options.allocationPreview,
      });
    }
    if (path.endsWith("/allocation-runs") && method === "POST") {
      return jsonResponse(
        {
          run_id: "00000000-0000-4000-8000-000000000401",
          campaign_id: campaignId,
          status: "planned",
          feasibility_status: "feasible",
          allocation_policy_version: "reviewer-allocation/v1",
          planner_version: "planner",
          source_snapshot_digest: "snapshot",
          pool_digest: "pool",
          planned_assignment_count: 24,
          distinct_subject_count: 12,
          reviewer_count: 2,
          created_at: new Date().toISOString(),
          published_at: null,
          lock_version: 1,
        },
        201,
      );
    }
    if (path.endsWith("/publish") && method === "POST") {
      return jsonResponse(
        {
          run_id: "00000000-0000-4000-8000-000000000401",
          status: "published",
          published_assignment_count: 120,
          created_assignment_count: 120,
          published_assignment_counts: { cases: 24, review_units: 120 },
          published_at: new Date().toISOString(),
        },
        201,
      );
    }

    return jsonResponse({});
  });
}

export function renderCampaignDetail(tenantId: string, campaignId: string) {
  const testRouter = createMemoryRouter(router.routes, {
    initialEntries: [`/t/${tenantId}/admin/campaigns/${campaignId}`],
  });
  return render(
    <AppProviders>
      <RouterProvider router={testRouter} />
    </AppProviders>,
  );
}
