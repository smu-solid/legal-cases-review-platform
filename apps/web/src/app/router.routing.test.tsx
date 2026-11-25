import { cleanup, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MeResponse } from "../api/types";
import {
  adminMe,
  enterAppAs,
  expectNoProtectedSampleContent,
  mockApiSession,
  mockAuthenticatedApiSession,
  mockDeniedApi,
  mockReviewerQueueErrorApi,
  renderAt,
  reviewerCampaignId,
  reviewerForbiddenTenantId,
  reviewerMe,
  tenantId,
} from "../test/routerScenarios";

describe("routing workflows", () => {
  it("does not leak protected content on unauthenticated direct route access", async () => {
    const protectedPaths = [
      `/t/${tenantId}/review`,
      `/t/${tenantId}/review/task/00000000-0000-4000-8000-000000000030`,
      `/t/${tenantId}/admin`,
      `/t/${tenantId}/adjudication`,
      `/t/${tenantId}/adjudication/00000000-0000-4000-8000-000000000040`,
    ];

    for (const path of protectedPaths) {
      renderAt(path);

      expect(await screen.findByRole("heading", { name: /^sign in$/i })).toBeInTheDocument();
      expectNoProtectedSampleContent();
      cleanup();
    }
  });

  it("shows an access-not-set-up state for a verified but unrostered identity", async () => {
    mockDeniedApi(403, "identity_not_rostered");
    renderAt("/");

    expect(await screen.findByRole("heading", { name: /access not set up/i })).toBeInTheDocument();
    expect(screen.getByText(/ask an administrator to add your email/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^sign in$/i })).not.toBeInTheDocument();
    expectNoProtectedSampleContent();
  });

  it("shows an account-disabled state for a suspended identity", async () => {
    mockDeniedApi(403, "account_disabled");
    renderAt(`/t/${tenantId}/review`);

    expect(await screen.findByRole("heading", { name: /account disabled/i })).toBeInTheDocument();
    expect(screen.getByText(/this account has been disabled/i)).toBeInTheDocument();
    expectNoProtectedSampleContent();
  });

  it("routes reviewers to the reviewer campaign queue when authenticated", async () => {
    await enterAppAs(reviewerMe);

    expect(
      await screen.findByRole("heading", { name: /your assigned campaigns/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/no campaigns assigned to you yet/i)).toBeInTheDocument();
    // The redundant "Assigned to you only" pill and the bottom sign-out were removed; account
    // controls live in the top-right menu and the reviewer footer shows only the brand line.
    expect(screen.queryByText(/^assigned to you only$/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sign out or switch account/i }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".app-footer-brand")).toBeInTheDocument();
    expect(screen.queryByText(/backend contract/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/reviewers see only their own work/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/synthetic demo/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/campaigns could not be loaded/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.queryByText(/public prosecutor v tan wei ming/i)).not.toBeInTheDocument();
    expect(screen.getByText("Reviewer Local")).toBeInTheDocument();
    expect(screen.queryByText(/Reviewer Local · api/i)).not.toBeInTheDocument();
  });

  it("redirects a stale/inaccessible tenant URL home instead of showing empty tenant data", async () => {
    mockApiSession(reviewerMe);
    const staleTenantId = "00000000-0000-4000-8000-0000000000ff";
    renderAt(`/t/${staleTenantId}/review`);

    // reviewerMe only belongs to `tenantId`, not `staleTenantId` — RequireTenant should bounce to
    // `/`, which re-derives the correct (`tenantId`) landing from `/me` rather than rendering the
    // stale tenant's (empty) queue page.
    expect(
      await screen.findByRole("heading", { name: /your assigned campaigns/i }),
    ).toBeInTheDocument();
  });

  it("shows a clear access state for an account with no tenant membership at all", async () => {
    const noTenantMe: MeResponse = {
      ...reviewerMe,
      active_tenant: null,
      default_landing: null,
      memberships: [],
    };
    mockApiSession(noTenantMe);
    renderAt(`/t/${tenantId}/review`);

    expect(
      await screen.findByRole("heading", { name: /not available for your role/i }),
    ).toBeInTheDocument();
  });

  it("shows reviewer-access copy for a queue 403 without also showing the empty state", async () => {
    mockReviewerQueueErrorApi(403, reviewerForbiddenTenantId);
    renderAt(`/t/${reviewerForbiddenTenantId}/review/campaigns/${reviewerCampaignId}`);

    expect(
      await screen.findByText(/you are not assigned reviewer access for this campaign/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/review queue could not be loaded/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no items in this view/i)).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/review/queue")),
    ).toHaveLength(1);
  });

  it("hides adjudication and blocks the route for non-adjudicators", async () => {
    mockAuthenticatedApiSession(reviewerMe);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(await screen.findByRole("heading", { name: /not available/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Adjudication" })).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.some(([input]) => String(input).includes("/review/adjudication-campaigns")),
    ).toBe(false);
  });

  it("routes superusers to the admin dashboard when authenticated", async () => {
    await enterAppAs(adminMe);

    expect(
      await screen.findByRole("heading", { name: /campaign and reviewer operations/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Admin" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reviewer queue" })).not.toBeInTheDocument();
  });

  it("blocks direct reviewer queue access for admins without reviewer capability", async () => {
    mockAuthenticatedApiSession(adminMe);
    renderAt(`/t/${tenantId}/review`);

    expect(await screen.findByRole("heading", { name: /not available/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /your assigned campaigns/i }),
    ).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.some(([input]) => String(input).includes("/review/queue")),
    ).toBe(false);
  });

  it("closes the account menu on Escape", async () => {
    const user = await enterAppAs(reviewerMe);
    await screen.findByRole("heading", { name: /your assigned campaigns/i });

    await user.click(screen.getByLabelText(/account menu/i));
    expect(await screen.findByRole("button", { name: /^sign out$/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^sign out$/i })).not.toBeInTheDocument();
    });
  });

  it("shows a usable session-expired state", async () => {
    renderAt("/session-expired");

    expect(await screen.findByRole("heading", { name: /session expired/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /check access again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in again/i })).toBeInTheDocument();
  });

  it("shows a neutral forbidden state", async () => {
    renderAt("/forbidden");

    expect(
      await screen.findByRole("heading", { name: /not available for your role/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/managed by your administrator/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /check access again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out or switch account/i })).toBeInTheDocument();
  });

  it("renders a neutral not-found page for unknown routes", async () => {
    renderAt("/not-a-real-route");

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });
});
