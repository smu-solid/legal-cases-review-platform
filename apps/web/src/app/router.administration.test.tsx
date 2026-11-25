import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  adminNoCampaignMe,
  adminNoCampaignTenantId,
  feasibleAvailability,
  jsonResponse,
  mockAdminStagingApi,
  mockAdminWithoutCampaigns,
  renderAt,
  tenantId,
} from "../test/routerScenarios";

describe("administration workflows", () => {
  it("lets admins invite a reviewer from the admin dashboard", async () => {
    mockAdminStagingApi();
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/admin`);

    expect(await screen.findByRole("heading", { name: /^invite reviewer$/i })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^reviewer email$/i), "invitee@example.test");
    await user.click(screen.getByRole("button", { name: /^add reviewer$/i }));

    expect(await screen.findByText(/reviewer added to the roster/i)).toBeInTheDocument();
    expect(screen.getByText(/activation link to choose a password/i)).toBeInTheDocument();
    expect(screen.getByText(/private activation link/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^pending$/i).length).toBeGreaterThan(0);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/admin\/tenants\/.*\/reviewers$/),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "invitee@example.test" }),
      }),
    );
  });

  it("offers one clear create-campaign-draft action and no CLI guidance when no campaign exists", async () => {
    mockAdminWithoutCampaigns();
    renderAt(`/t/${adminNoCampaignTenantId}/admin`);

    expect(await screen.findByRole("heading", { name: /^your campaigns$/i })).toBeInTheDocument();
    expect(
      screen.getAllByText(/groups the cases, fields, reviewers, and assignments/i).length,
    ).toBeGreaterThan(0);
    // Real backend-exposed authoring is available (campaign_manager capability): one create-draft
    // action drawing from the preloaded pool, no "Load cases from database"/synthetic-fixture
    // wording, and no "run make seed" CLI guidance on this screen.
    expect(screen.getByRole("button", { name: /^create campaign draft$/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^load cases from database$/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/import synthetic fixture/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/make seed SOURCE=sample_a/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/make seed-smoke/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/the cli seed is not run from this screen/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/cases are preloaded by an ops\/local command, not from this page/i),
    ).toBeInTheDocument();
    // Responsive layout smoke (see CampaignDetailPage.test.tsx for the jsdom-limitation note):
    // built from the shared admin layout primitives, not a one-off narrow `.page-panel`.
    expect(document.querySelector(".admin-page")).toBeInTheDocument();
    expect(document.querySelectorAll(".admin-card").length).toBeGreaterThan(0);
    expect(document.querySelector(".admin-form-grid")).toBeInTheDocument();
  });

  it("shows an eligibility preview from the pool as source/field/case-count inputs change", async () => {
    mockAdminWithoutCampaigns();
    renderAt(`/t/${adminNoCampaignTenantId}/admin`);

    await screen.findByLabelText(/^campaign key$/i);
    expect(await screen.findAllByText("12 cases")).toHaveLength(3);
    expect(screen.getByText(/available in pool/i)).toBeInTheDocument();
    expect(screen.getByText(/new campaign total/i)).toBeInTheDocument();
  });

  it("creates a campaign draft from the eligible pool with a requested case count", async () => {
    mockAdminWithoutCampaigns();
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/auth/me")) {
        return jsonResponse(adminNoCampaignMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      if (url.includes("/review/campaign-case-filters/apply") && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as {
          case_filter?: { version?: string; all?: unknown[] };
        };
        return jsonResponse({
          normalized_case_filter: body.case_filter ?? { version: "v1", all: [] },
          source_pool_cases_count: 12,
          case_filter_matching_count: 12,
          matching_count_by_source: { sample_a: 12, sample_b: 0 },
          catalog_result_digest: "no_catalog",
          receipt_expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
          applied_filter_token: "router-create-filter-token",
        });
      }
      if (url.includes("/review/campaign-availability") && method === "POST") {
        return jsonResponse(feasibleAvailability());
      }
      if (url.endsWith("/review/campaigns") && method === "POST") {
        return jsonResponse(
          {
            campaign_id: "00000000-0000-4000-8000-000000000402",
            campaign_key: "local-staging",
            campaign_name: "Local staging",
            status: "draft",
            total_units: 0,
            availability: feasibleAvailability(),
            // Keep this legacy response on the dashboard: this test only verifies the authored
            // request body, while current backend empty-pool responses are rejected with 422.
            not_ready_for_publish: true,
          },
          201,
        );
      }
      if (url.includes("/review/campaign-progress")) {
        return jsonResponse({ tenant_id: tenantId, items: [] });
      }
      return jsonResponse({});
    });
    const user = userEvent.setup();
    renderAt(`/t/${adminNoCampaignTenantId}/admin`);

    const campaignKeyInput = await screen.findByLabelText(/^campaign key$/i);
    const campaignNameInput = screen.getByLabelText(/^campaign name$/i);
    await user.clear(campaignKeyInput);
    await user.type(campaignKeyInput, "local-staging");
    await user.clear(campaignNameInput);
    await user.type(campaignNameInput, "Local staging");
    expect(screen.queryByLabelText(/^source$/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^create campaign draft$/i }));

    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/review\/campaigns$/),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            campaign_key: "local-staging",
            campaign_name: "Local staging",
            reviews_per_case: 2,
            review_scope: null,
            requested_case_count: "all",
            synthesize_missing_values: false,
            case_filter: { version: "v1", all: [] },
            confirm_smaller_count: false,
            confirm_remaining_fields_only: false,
          }),
        }),
      ),
    );
  });

  it("shows a duplicate-key error on 409 and clears it immediately when the key or name changes", async () => {
    mockAdminWithoutCampaigns();
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/auth/me")) {
        return jsonResponse(adminNoCampaignMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.includes("/admin/tenants/") && url.includes("/reviewers")) {
        return jsonResponse({ items: [], next_cursor: null });
      }
      if (url.includes("/review/campaign-availability") && method === "POST") {
        return jsonResponse(feasibleAvailability());
      }
      if (url.endsWith("/review/campaigns") && method === "POST") {
        return jsonResponse(
          {
            type: "https://errors.review.invalid/campaign/key/exists",
            title: "Conflict",
            status: 409,
            code: "campaign_key_exists",
            detail: "A campaign with this key already exists in the tenant.",
          },
          409,
        );
      }
      if (url.includes("/review/campaign-progress")) {
        return jsonResponse({ tenant_id: adminNoCampaignTenantId, items: [] });
      }

      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${adminNoCampaignTenantId}/admin`);

    const campaignKeyInput = await screen.findByLabelText(/^campaign key$/i);
    await user.clear(campaignKeyInput);
    await user.type(campaignKeyInput, "dup-key");
    await user.click(screen.getByRole("button", { name: /^create campaign draft$/i }));

    expect(await screen.findByText(/a campaign with this key already exists/i)).toBeInTheDocument();

    await user.type(campaignKeyInput, "-2");

    expect(screen.queryByText(/a campaign with this key already exists/i)).not.toBeInTheDocument();
  });

  it("validates invite email before calling the roster API", async () => {
    mockAdminStagingApi();
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/admin`);

    const emailInput = await screen.findByLabelText(/^reviewer email$/i);
    await user.type(emailInput, "invitee@local");
    await user.click(screen.getByRole("button", { name: /^add reviewer$/i }));

    expect(await screen.findByText(/enter a valid reviewer email address/i)).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("aria-invalid", "true");
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/reviewers") &&
            (init as RequestInit | undefined)?.method === "POST",
        ),
    ).toBe(false);
  });

  it("surfaces per-reviewer workload columns for active reviewers", async () => {
    mockAdminStagingApi();
    renderAt(`/t/${tenantId}/admin`);

    // Active roster row carries the backend workload counts (assigned/submitted/claimed/released).
    expect(
      await screen.findByRole("row", { name: /Reviewer One reviewer Yes 7 3 2 1/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("row", { name: /Reviewer Two reviewer Yes 5 1 1 0/i }),
    ).toBeInTheDocument();
  });
});
