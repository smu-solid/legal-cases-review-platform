import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CapabilityFlags, MeResponse } from "../../api/types";
import { AppProviders } from "../../app/AppProviders";
import { queryClient } from "../../app/queryClient";
import { router } from "../../app/router";

const TENANT_ID = "00000000-0000-4000-8000-000000005001";
const CAMPAIGN_ID = "00000000-0000-4000-8000-000000005002";

function reviewerMe(): MeResponse {
  const caps: CapabilityFlags = {
    can_administer: false,
    can_review: true,
    can_adjudicate: false,
    can_invite_reviewers: false,
    can_allocate: false,
    can_manage_campaigns: false,
  };
  return {
    id: "00000000-0000-4000-8000-000000005003",
    email: "reviewer@local.test",
    display_name: "Reviewer Local",
    subject: "reviewer@local.test",
    status: "active",
    global_roles: [],
    global_capabilities: [],
    active_tenant: TENANT_ID,
    default_landing: "/review",
    capabilities: caps,
    session_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    memberships: [
      {
        membership_id: "00000000-0000-4000-8000-000000005004",
        tenant_id: TENANT_ID,
        tenant_key: "local",
        roles: ["reviewer"],
        capabilities: ["review:read"],
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

function caseItem(n: number) {
  return {
    case_id: `00000000-0000-4000-8000-00000000600${n}`,
    anchor_assignment_id: `00000000-0000-4000-8000-00000000700${n}`,
    case_title: `Case ${n}`,
    neutral_citation_display: `[2020] SGHC ${n}`,
    reported_citation_display: null,
    status: "in_progress",
    fields_assigned: 5,
    fields_submitted: n,
  };
}

// The campaign summary's own-work counts (2 + 3 + 4 = 9) are the only total the API exposes for a
// reviewer's assigned cases; the case-queue pages themselves carry just has_more/next_cursor.
function mockQueueApi(options: { assignedTotal?: () => number } = {}) {
  vi.mocked(globalThis.fetch).mockImplementation((input) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;

    if (path.endsWith("/auth/me")) {
      return jsonResponse(reviewerMe());
    }
    if (path.endsWith("/auth/csrf")) {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    if (path.endsWith(`/review/campaigns/${CAMPAIGN_ID}/cases`)) {
      if (url.searchParams.get("cursor")) {
        return jsonResponse({
          campaign_id: CAMPAIGN_ID,
          items: [caseItem(3), caseItem(4)],
          next_cursor: null,
          has_more: false,
        });
      }
      return jsonResponse({
        campaign_id: CAMPAIGN_ID,
        items: [caseItem(1), caseItem(2)],
        next_cursor: "cursor-2",
        has_more: true,
      });
    }
    if (path.endsWith("/review/campaigns")) {
      const assignedTotal = options.assignedTotal?.() ?? 9;
      return jsonResponse({
        campaigns: [
          {
            campaign_id: CAMPAIGN_ID,
            campaign_name: "Local Pilot",
            not_started_count: assignedTotal - 7,
            in_progress_count: 3,
            completed_count: 4,
          },
        ],
        next_cursor: null,
        has_more: false,
      });
    }
    if (path.endsWith("/review/queue")) {
      return jsonResponse({ items: [], next_cursor: null, has_more: false });
    }
    return jsonResponse({ detail: `unmocked path ${path}` }, 404);
  });
}

describe("ReviewerQueuePage assigned-case total and pagination", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // The app's React Query client is a module-level singleton; clear its cache between tests so
    // one test's cached campaign/case-queue data (same tenant/campaign id across this file) never
    // bleeds into the next test's assertions (see app/router.test.tsx for the same pattern).
    queryClient.clear();
  });

  it("shows the reviewer's total assigned-case count from the campaign summary", async () => {
    mockQueueApi();
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: [`/t/${TENANT_ID}/review/campaigns/${CAMPAIGN_ID}`],
    });
    render(
      <AppProviders>
        <RouterProvider router={memoryRouter} />
      </AppProviders>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Your assigned cases (9)" })).toBeInTheDocument();
    });
  });

  it("renders a numbered pager and pages through keyset results on demand", async () => {
    mockQueueApi({ assignedTotal: () => 14 });
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: [`/t/${TENANT_ID}/review/campaigns/${CAMPAIGN_ID}`],
    });
    render(
      <AppProviders>
        <RouterProvider router={memoryRouter} />
      </AppProviders>,
    );

    await waitFor(() => {
      expect(screen.getByText(/\[2020\] SGHC 1 · Case 1/)).toBeInTheDocument();
    });
    expect(screen.getByText(/\[2020\] SGHC 2 · Case 2/)).toBeInTheDocument();
    // Numbered pager, not the old infinite-scroll button.
    expect(screen.queryByRole("button", { name: "Show more cases" })).not.toBeInTheDocument();
    // The range numbers live inside <strong> children, so match on the paragraph's full
    // textContent rather than a single text node (and scope to the status paragraph itself so
    // ancestor elements whose textContent also contains the substring don't produce duplicates).
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "P" &&
          element.classList.contains("pager-status") &&
          /Showing 1–2 of 14/.test(element.textContent ?? ""),
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Page 2" }));
    await waitFor(() => {
      expect(screen.getByText(/\[2020\] SGHC 3 · Case 3/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/\[2020\] SGHC 1 · Case 1/)).not.toBeInTheDocument();
  });

  it("requests the reviewer-selected page size and persists it", async () => {
    const caseRequests: URL[] = [];
    mockQueueApi();
    const baseImplementation = vi.mocked(globalThis.fetch).getMockImplementation()!;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith(`/review/campaigns/${CAMPAIGN_ID}/cases`)) {
        caseRequests.push(url);
      }
      return baseImplementation(input, init);
    });
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: [`/t/${TENANT_ID}/review/campaigns/${CAMPAIGN_ID}`],
    });
    render(
      <AppProviders>
        <RouterProvider router={memoryRouter} />
      </AppProviders>,
    );

    const selector = await screen.findByRole("combobox", { name: "Cases per page" });
    await waitFor(() =>
      expect(caseRequests.some((url) => url.searchParams.get("limit") === "10")).toBe(true),
    );
    fireEvent.change(selector, { target: { value: "20" } });
    await waitFor(() =>
      expect(caseRequests.some((url) => url.searchParams.get("limit") === "20")).toBe(true),
    );
    expect(window.localStorage.getItem(`reviewer-case-page-size:${reviewerMe().id}`)).toBe("20");
  });

  it("changing page size restarts from a null cursor instead of appending stale pages", async () => {
    const caseRequests: URL[] = [];
    mockQueueApi({ assignedTotal: () => 14 });
    const baseImplementation = vi.mocked(globalThis.fetch).getMockImplementation()!;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith(`/review/campaigns/${CAMPAIGN_ID}/cases`)) {
        caseRequests.push(url);
      }
      return baseImplementation(input, init);
    });
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: [`/t/${TENANT_ID}/review/campaigns/${CAMPAIGN_ID}`],
    });
    render(
      <AppProviders>
        <RouterProvider router={memoryRouter} />
      </AppProviders>,
    );

    // Paging to page 2 fetches the next keyset cursor.
    fireEvent.click(await screen.findByRole("button", { name: "Page 2" }));
    await waitFor(() =>
      expect(caseRequests.some((url) => url.searchParams.get("cursor") === "cursor-2")).toBe(true),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Cases per page" }), {
      target: { value: "50" },
    });
    await waitFor(() => {
      const latest = caseRequests.at(-1)!;
      expect(latest.searchParams.get("limit")).toBe("50");
      expect(latest.searchParams.get("cursor")).toBeNull();
    });
  });

  it("notifies on focus when assigned cases grew and refreshes from a null cursor on demand", async () => {
    let assignedTotal = 9;
    const caseRequests: URL[] = [];
    mockQueueApi({ assignedTotal: () => assignedTotal });
    const baseImplementation = vi.mocked(globalThis.fetch).getMockImplementation()!;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith(`/review/campaigns/${CAMPAIGN_ID}/cases`)) {
        caseRequests.push(url);
      }
      return baseImplementation(input, init);
    });
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: [`/t/${TENANT_ID}/review/campaigns/${CAMPAIGN_ID}`],
    });
    render(
      <AppProviders>
        <RouterProvider router={memoryRouter} />
      </AppProviders>,
    );

    await screen.findByRole("heading", { name: "Your assigned cases (9)" });
    const initialCaseRequestCount = caseRequests.length;
    assignedTotal = 11;
    fireEvent.focus(window);

    expect(
      await screen.findByText(/2 new cases were added to this campaign — refresh to see them/i),
    ).toBeInTheDocument();
    expect(caseRequests).toHaveLength(initialCaseRequestCount);

    fireEvent.click(screen.getByRole("button", { name: /refresh cases/i }));
    await waitFor(() => expect(caseRequests.length).toBeGreaterThan(initialCaseRequestCount));
    expect(caseRequests.at(-1)?.searchParams.get("cursor")).toBeNull();
    expect(screen.queryByText(/new cases were added to this campaign/i)).not.toBeInTheDocument();
  });
});
