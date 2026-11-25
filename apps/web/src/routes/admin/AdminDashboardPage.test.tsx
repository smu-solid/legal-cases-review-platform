import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { CapabilityFlags, MeResponse } from "../../api/types";
import { AppProviders } from "../../app/AppProviders";
import { router } from "../../app/router";

let idSeq = 0;
function freshTenantId() {
  idSeq += 1;
  return `00000000-0000-4000-8000-0000004${String(idSeq).padStart(4, "0")}`;
}

function caps(overrides: Partial<CapabilityFlags> = {}): CapabilityFlags {
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

function adminMeFor(tenantId: string): MeResponse {
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

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

function mockDashboardApi(
  tenantId: string,
  options: {
    inviteHandler?: () => Promise<Response>;
    availability?: Record<string, unknown>;
    filterMatchCount?: number;
    progressItems?: Record<string, unknown>[];
  } = {},
) {
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
    if (path.includes("/admin/tenants/") && path.endsWith("/reviewers") && method === "POST") {
      return options.inviteHandler
        ? options.inviteHandler()
        : jsonResponse(
            {
              user_id: "00000000-0000-4000-8000-000000000501",
              membership_id: "00000000-0000-4000-8000-000000000502",
              user_status: "pending",
              membership_status: "pending",
              invitation_email: "sent",
            },
            201,
          );
    }
    if (path.includes("/admin/tenants/") && path.endsWith("/reviewers")) {
      return jsonResponse({ items: [], next_cursor: null, has_more: false });
    }
    if (path.includes("/review/campaign-progress")) {
      return jsonResponse({ tenant_id: tenantId, items: options.progressItems ?? [] });
    }
    if (path.includes("/review/scope-catalog")) {
      return jsonResponse({
        tenant_id: tenantId,
        contract_version: "campaign-scope-catalog/v1",
        groups: [],
        review_kinds: [],
      });
    }
    if (path.includes("/review/campaign-case-filters/apply")) {
      const request = JSON.parse(String(init?.body ?? "{}")) as {
        case_filter?: { version?: string; all?: unknown[] };
      };
      const count = request.case_filter?.all?.length
        ? (options.filterMatchCount ?? 3)
        : Number(options.availability?.eligible_cases_count ?? 0);
      return jsonResponse({
        normalized_case_filter: request.case_filter ?? { version: "v1", all: [] },
        source_pool_cases_count: count,
        case_filter_matching_count: count,
        matching_count_by_source: { sample_a: count, sample_b: count },
        unidentifiable_pool_units_count: 0,
        identity_unavailable_cases_count: 0,
        identity_conflict_cases_count: 0,
        catalog_result_digest: "no_catalog",
        receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        applied_filter_token: "test-applied-filter-token",
        schema_version: "campaign-case-filter-apply/v1",
      });
    }
    if (path.includes("/review/campaign-case-ids/apply")) {
      const request = JSON.parse(String(init?.body ?? "{}")) as {
        case_id_selection: { case_ids: string[] };
      };
      const unmatched = request.case_id_selection.case_ids.filter((caseId) => caseId === "MISSING");
      const matchingCount = request.case_id_selection.case_ids.length - unmatched.length;
      return jsonResponse({
        normalized_case_id_selection: request.case_id_selection,
        source_pool_cases_count: 8,
        uploaded_unique_count: request.case_id_selection.case_ids.length,
        case_id_matching_count: matchingCount,
        matching_count_by_source: { sample_a: matchingCount, sample_b: 0 },
        unmatched_case_ids: unmatched,
        receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        applied_case_id_token: "test-case-id-token",
        schema_version: "campaign-case-id-apply/v1",
      });
    }
    if (path.includes("/review/campaign-case-filters/corrections")) {
      return jsonResponse({
        typed_value: "",
        suggestions: [],
        schema_version: "campaign-case-filter-corrections/v1",
      });
    }
    if (path.includes("/review/campaign-availability")) {
      const count = Number(options.availability?.eligible_cases_count ?? 0);
      return jsonResponse({
        requested_case_count: 0,
        requested_field_scope: [],
        eligible_cases_count: 0,
        source_pool_cases_count: count,
        case_filter_matching_count: count,
        case_filter_excluded_count: 0,
        projected_campaign_cases_count: count,
        eligible_review_units_count: 0,
        unavailable_cases_count: 0,
        unavailable_review_units_count: 0,
        fields_fully_exhausted: [],
        fields_partially_available: [],
        cases_available_for_all_selected_fields: 0,
        cases_available_for_some_selected_fields_only: 0,
        feasibility: "infeasible_no_cases",
        infeasible_message: "No cases are available.",
        schema_version: "campaign-availability/v1",
        ...options.availability,
      });
    }
    return jsonResponse({});
  });
}

function renderDashboard(tenantId: string) {
  const testRouter = createMemoryRouter(router.routes, {
    initialEntries: [`/t/${tenantId}/admin`],
  });
  return render(
    <AppProviders>
      <RouterProvider router={testRouter} />
    </AppProviders>,
  );
}

async function submitInvite(user: ReturnType<typeof userEvent.setup>, email: string) {
  const input = await screen.findByLabelText(/reviewer email/i);
  await user.type(input, email);
  await user.click(screen.getByRole("button", { name: /^add reviewer$/i }));
}

describe("admin dashboard reviewer invitation", () => {
  it("shows sent copy when the backend confirms a new invitation email was accepted for sending", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId);
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await submitInvite(user, "new-reviewer@example.test");

    expect(await screen.findByText(/invitation email was sent/i)).toBeInTheDocument();
  });

  it("shows resent copy when the backend reports a reminder to a still-pending reviewer", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      inviteHandler: () =>
        jsonResponse(
          {
            user_id: "00000000-0000-4000-8000-000000000501",
            membership_id: "00000000-0000-4000-8000-000000000502",
            user_status: "pending",
            membership_status: "pending",
            invitation_email: "resent",
          },
          201,
        ),
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await submitInvite(user, "pending-reviewer@example.test");

    expect(await screen.findByText(/reminder invitation email was re-sent/i)).toBeInTheDocument();
  });

  it("shows not-sent copy and never claims delivery when the reviewer is already active", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      inviteHandler: () =>
        jsonResponse(
          {
            user_id: "00000000-0000-4000-8000-000000000501",
            membership_id: "00000000-0000-4000-8000-000000000502",
            user_status: "active",
            membership_status: "active",
            invitation_email: "not_sent_already_active",
          },
          201,
        ),
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await submitInvite(user, "already-active@example.test");

    expect(
      await screen.findByText(/already active, so no invitation email was sent/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/an invitation email was sent/i)).not.toBeInTheDocument();
  });

  it("shows a delivery-failure message and never claims success when the invitation email fails", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      inviteHandler: () =>
        jsonResponse(
          {
            type: "https://errors.review.invalid/admin/invitation-email-delivery-failed",
            title: "Invitation email failed",
            status: 502,
            code: "invitation_email_delivery_failed",
            detail: "The invitation email could not be delivered, so the reviewer was not added.",
          },
          502,
        ),
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await submitInvite(user, "undeliverable@example.test");

    expect(
      await screen.findByText(
        /invitation email could not be delivered, so the reviewer was not added/i,
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText(/invitation email was sent/i)).not.toBeInTheDocument();
    });
  });
});

describe("admin dashboard campaign availability", () => {
  it("blocks campaign creation and shows a clear red error when the pool is empty", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId);
    renderDashboard(tenantId);

    expect(await screen.findByText(/no cases are available/i)).toHaveClass("form-error");
    expect(screen.getByRole("button", { name: /^create campaign draft$/i })).toBeDisabled();
  });

  it("shows the available and projected campaign counts before creation", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        requested_case_count: "all",
        eligible_cases_count: 8,
        eligible_review_units_count: 80,
        cases_available_for_all_selected_fields: 8,
        feasibility: "feasible_exact",
        infeasible_message: null,
      },
    });
    renderDashboard(tenantId);

    expect(await screen.findAllByText("8 cases")).toHaveLength(3);
    expect(screen.getByText(/available in pool/i)).toBeInTheDocument();
    expect(screen.getByText(/matches case selection/i)).toBeInTheDocument();
    expect(screen.getByText(/new campaign total/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^create campaign draft$/i })).toBeEnabled();
  });

  it("keeps the campaign reviews-per-case value fixed at two", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        requested_case_count: "all",
        eligible_cases_count: 8,
        eligible_review_units_count: 80,
        cases_available_for_all_selected_fields: 8,
        feasibility: "feasible_exact",
        infeasible_message: null,
      },
    });
    renderDashboard(tenantId);

    const reviewsPerCase = await screen.findByLabelText(/^number of reviews per case$/i);
    expect(reviewsPerCase).toHaveValue(2);
    expect(reviewsPerCase).toBeDisabled();
    expect(reviewsPerCase).toHaveClass("frozen-input");
  });

  it("names campaigns and fields that will be omitted from an all-fields campaign", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        requested_case_count: "all",
        eligible_cases_count: 10,
        eligible_review_units_count: 50,
        cases_available_for_all_selected_fields: 10,
        feasibility: "feasible_exact",
        infeasible_message: null,
        overlap_cases_count: 10,
        overlap_group_counts: [{ group_id: "case_metadata", cases_count: 10 }],
        overlap_campaigns: [
          {
            campaign_id: "00000000-0000-4000-8000-000000000777",
            campaign_key: "c1",
            campaign_name: "Campaign 1",
            cases_count: 10,
            group_counts: [{ group_id: "case_metadata", cases_count: 10 }],
          },
        ],
      },
    });
    renderDashboard(tenantId);

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent(/some fields are already in other campaigns/i);
    expect(warning).toHaveTextContent(/campaign 1.*c1.*case_metadata \(10 cases\)/i);
    expect(warning).toHaveTextContent(/omitted from this new campaign/i);
    expect(warning).toHaveTextContent(/existing campaigns and their fields will not be changed/i);
    expect(screen.getByRole("button", { name: /^create campaign draft$/i })).toBeEnabled();
  });

  it("keeps edited filters unapplied until Apply filters succeeds", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        eligible_cases_count: 8,
        projected_campaign_cases_count: 8,
        feasibility: "feasible_exact",
        infeasible_message: null,
      },
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    const createButton = await screen.findByRole("button", { name: /^create campaign draft$/i });
    await waitFor(() => expect(createButton).toBeEnabled());
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) =>
          String(input).includes("/review/campaign-case-filters/apply"),
        ),
    ).toHaveLength(0);
    const exportButton = screen.getByRole("button", { name: /^export case ids$/i });
    expect(exportButton).toBeEnabled();
    await user.click(screen.getByRole("button", { name: /^add filter$/i }));
    await user.type(screen.getByPlaceholderText("e.g. Criminal"), "Criminal");

    expect(createButton).toBeDisabled();
    expect(exportButton).toBeDisabled();
    expect(screen.getByText(/filters changed — apply/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^apply filters$/i }));
    expect(await screen.findByText(/3 cases in the pool match/i)).toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) =>
          String(input).includes("/review/campaign-case-filters/apply"),
        ),
    ).toHaveLength(1);
    await waitFor(() => expect(createButton).toBeEnabled());
    expect(exportButton).toBeEnabled();
  });

  it("keeps case ID export disabled when an applied filter has no matches", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      filterMatchCount: 0,
      availability: { eligible_cases_count: 0, feasibility: "infeasible_no_cases" },
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await user.click(await screen.findByRole("button", { name: /^add filter$/i }));
    await user.type(screen.getByPlaceholderText("e.g. Criminal"), "No matches");
    await user.click(screen.getByRole("button", { name: /^apply filters$/i }));
    expect(await screen.findByText(/0 cases in the pool/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /^export case ids$/i })).toBeDisabled();
  });

  it("normalizes one file and retains it while changing the field selection", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        eligible_cases_count: 1,
        projected_campaign_cases_count: 1,
        feasibility: "feasible_exact",
        infeasible_message: null,
      },
    });
    const user = userEvent.setup();
    const clipboardWrite = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderDashboard(tenantId);

    await user.click(await screen.findByRole("tab", { name: /upload case ids/i }));
    const file = new File(["CASE-1\nMISSING\nCASE-1\nCASE-2\n"], "cases.txt", {
      type: "text/plain",
    });
    const input = screen.getByLabelText(/drag and drop a \.txt file here/i);
    await user.upload(input, file);

    expect(await screen.findByText(/2 of 3 unique uploaded case ids match/i)).toBeInTheDocument();
    expect(screen.getAllByText("cases.txt").length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/case ids not matched/i)).toHaveValue("MISSING");
    await user.click(screen.getByRole("button", { name: /copy unmatched case ids/i }));
    expect(clipboardWrite).toHaveBeenCalledWith("MISSING");
    expect(screen.getByText(/copied to clipboard/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /remove cases\.txt/i }));
    expect(screen.queryByRole("button", { name: /remove cases\.txt/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no file chosen/i)).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/drag and drop a \.txt file here/i), file);
    expect(await screen.findByText(/2 of 3 unique uploaded case ids match/i)).toBeInTheDocument();

    const uploadApplyCount = vi
      .mocked(globalThis.fetch)
      .mock.calls.filter(([input]) => String(input).includes("/campaign-case-ids/apply")).length;
    await user.selectOptions(screen.getByLabelText(/^fields$/i), "selected");
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/campaign-case-ids/apply")),
    ).toHaveLength(uploadApplyCount);

    expect(screen.getByRole("button", { name: /remove cases\.txt/i })).toBeInTheDocument();
  });

  it("rejects multiple dropped files and highlights a valid single-file drop", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      availability: {
        eligible_cases_count: 1,
        projected_campaign_cases_count: 1,
        feasibility: "feasible_exact",
        infeasible_message: null,
      },
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    await user.click(await screen.findByRole("tab", { name: /upload case ids/i }));
    const input = screen.getByLabelText(/drag and drop a \.txt file here/i);
    const dropzone = input.closest("label");
    expect(dropzone).not.toBeNull();
    const file = new File(["CASE-1\n"], "dropped.txt", { type: "text/plain" });
    const extraFile = new File(["CASE-2\n"], "extra.txt", { type: "text/plain" });

    fireEvent.drop(dropzone as HTMLLabelElement, {
      dataTransfer: { files: [file, extraFile] },
    });
    expect(screen.getByText(/choose exactly one \.txt file/i)).toBeInTheDocument();

    fireEvent.dragEnter(dropzone as HTMLLabelElement, { dataTransfer: { files: [file] } });
    expect(dropzone).toHaveClass("is-dragging");
    fireEvent.drop(dropzone as HTMLLabelElement, { dataTransfer: { files: [file] } });

    expect(dropzone).not.toHaveClass("is-dragging");
    expect(await screen.findByText(/1 of 1 unique uploaded case ids match/i)).toBeInTheDocument();
    expect(screen.getAllByText("dropped.txt").length).toBeGreaterThan(0);
  });
});

function progressItem(
  overrides: Record<string, unknown> & { campaign_id: string },
): Record<string, unknown> {
  return {
    campaign_name: "Campaign",
    campaign_key: "campaign-key",
    campaign_status: "draft",
    cases_total: 0,
    total_units: 0,
    unit_status_counts: { pending: 0, in_review: 0, in_adjudication: 0, resolved: 0 },
    total_assignments: 0,
    assignment_status_counts: { claimed: 0, submitted: 0, released: 0 },
    reviewers_total: 0,
    case_reviewer_slots_total: 0,
    case_reviewer_completions: 0,
    cases_fully_complete_count: 0,
    completed: false,
    schema_version: "campaign-progress/v1",
    ...overrides,
  };
}

describe("admin dashboard campaign list", () => {
  it("hides closed campaigns from the list by default and reveals them via the toggle", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      progressItems: [
        progressItem({
          campaign_id: "00000000-0000-4000-8000-000000000601",
          campaign_name: "Active Campaign",
          campaign_status: "draft",
        }),
        progressItem({
          campaign_id: "00000000-0000-4000-8000-000000000602",
          campaign_name: "Retired Campaign",
          campaign_status: "closed",
        }),
      ],
    });
    const user = userEvent.setup();
    renderDashboard(tenantId);

    expect(await screen.findByText("Active Campaign")).toBeInTheDocument();
    expect(screen.queryByText("Retired Campaign")).not.toBeInTheDocument();

    const toggle = screen.getByRole("checkbox", { name: /show closed \(1\)/i });
    await user.click(toggle);

    expect(await screen.findByText("Retired Campaign")).toBeInTheDocument();
  });

  it("does not show the show-closed toggle when there are no closed campaigns", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      progressItems: [
        progressItem({
          campaign_id: "00000000-0000-4000-8000-000000000603",
          campaign_name: "Only Campaign",
          campaign_status: "draft",
        }),
      ],
    });
    renderDashboard(tenantId);

    await screen.findByText("Only Campaign");
    expect(screen.queryByRole("checkbox", { name: /show closed/i })).not.toBeInTheDocument();
  });

  it("exposes the create-campaign action when all campaigns are closed, without requiring Show closed", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      progressItems: [
        progressItem({
          campaign_id: "00000000-0000-4000-8000-000000000605",
          campaign_name: "Retired Campaign",
          campaign_status: "closed",
        }),
      ],
    });
    renderDashboard(tenantId);

    expect(await screen.findByText(/all campaigns are closed/i)).toBeInTheDocument();
    expect(screen.queryByText("Retired Campaign")).not.toBeInTheDocument();

    const toggle = screen.getByRole("checkbox", { name: /show closed \(1\)/i });
    expect(toggle).not.toBeChecked();

    expect(screen.getByRole("button", { name: /^create campaign draft$/i })).toBeInTheDocument();
  });

  it("shows a Completed badge for a campaign marked completed", async () => {
    const tenantId = freshTenantId();
    mockDashboardApi(tenantId, {
      progressItems: [
        progressItem({
          campaign_id: "00000000-0000-4000-8000-000000000604",
          campaign_name: "Finished Campaign",
          campaign_status: "published",
          completed: true,
        }),
      ],
    });
    renderDashboard(tenantId);

    expect(await screen.findByText(/published · completed/i)).toBeInTheDocument();
  });
});
