import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AdjudicationCampaignCasesPage } from "./AdjudicationCampaignCasesPage";

const tenantId = "00000000-0000-4000-8000-000000000101";
const campaignId = "00000000-0000-4000-8000-000000000102";

function progress(overrides: Record<string, number> = {}) {
  return {
    total_scoped_fields: 2,
    personal_responsibility_fields: 2,
    completed_responsibility_fields: 1,
    submitted_fields: 1,
    waived_fields: 0,
    not_required_fields: 0,
    pending_fields: 1,
    future_eligible_fields: 0,
    ...overrides,
  };
}

describe("AdjudicationCampaignCasesPage", () => {
  it("shows not-required cases under All without adding a separate tab", async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          campaign: {
            campaign_id: campaignId,
            campaign_key: "pilot",
            campaign_name: "Pilot",
            waiting_count: 1,
            in_progress_count: 0,
            finished_count: 1,
            not_required_count: 1,
            total_case_count: 3,
          },
          counts: { all: 3, waiting: 1, in_progress: 0, finished: 1, not_required: 1 },
          items: [
            {
              case_id: "waiting",
              campaign_id: campaignId,
              case_title: "Waiting case",
              neutral_citation_display: "[2024] SGCA 1",
              reported_citation_display: "[2024] 1 REP 10",
              status: "waiting",
              completion_kind: null,
              status_reason_code: "awaiting_future_participation",
              status_reason: "Reviews are still in progress",
              progress: progress({
                submitted_fields: 0,
                completed_responsibility_fields: 0,
                pending_fields: 0,
                future_eligible_fields: 2,
              }),
              field_progress: [
                {
                  review_unit_id: "00000000-0000-4000-8000-000000000201",
                  item_label: "Case title",
                  submitted_reviews: 2,
                  required_reviews: 3,
                  state: "awaiting_reviews",
                  pending_reviewers: [
                    {
                      display_name: "A reviewer with a deliberately long display name",
                      email: "named-reviewer@example.test",
                    },
                    {
                      display_name: null,
                      email: "fallback-reviewer@example.test",
                    },
                  ],
                },
                {
                  review_unit_id: "00000000-0000-4000-8000-000000000204",
                  item_label: "Judgment author",
                  submitted_reviews: 0,
                  required_reviews: 3,
                  state: "awaiting_reviews",
                  pending_reviewers: [],
                },
              ],
              workspace_adjudication_id: null,
              workspace_mode: null,
            },
            {
              case_id: "finished",
              campaign_id: campaignId,
              case_title: "Finished case",
              status: "finished",
              completion_kind: "completed",
              status_reason_code: "completed_by_me",
              status_reason: "Complete",
              progress: progress({
                submitted_fields: 2,
                completed_responsibility_fields: 2,
                pending_fields: 0,
              }),
              field_progress: [
                {
                  review_unit_id: "00000000-0000-4000-8000-000000000202",
                  item_label: "Neutral citation",
                  submitted_reviews: 3,
                  required_reviews: 3,
                  state: "adjudicated_by_me",
                },
              ],
              workspace_adjudication_id: "00000000-0000-4000-8000-000000000103",
              workspace_mode: "read_only",
            },
            {
              case_id: "not-required",
              campaign_id: campaignId,
              case_title: "Not required case",
              status: "not_required",
              completion_kind: "not_required",
              status_reason_code: "not_required",
              status_reason: "No adjudication is assigned to you for this case",
              progress: progress({
                total_scoped_fields: 2,
                personal_responsibility_fields: 0,
                completed_responsibility_fields: 0,
                submitted_fields: 0,
                pending_fields: 0,
                not_required_fields: 2,
              }),
              // Older additive-contract responses may omit field_progress while a backend process
              // is rolling forward; the case list must remain usable during that compatibility gap.
              workspace_adjudication_id: null,
              workspace_mode: null,
            },
          ],
          next_cursor: null,
          has_more: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[
            `/t/${tenantId}/adjudication/campaigns/${campaignId}?status=not_required`,
          ]}
        >
          <Routes>
            <Route
              path="/t/:tenantId/adjudication/campaigns/:campaignId"
              element={<AdjudicationCampaignCasesPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Pilot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "all (3)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /not required/i })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "[2024] SGCA 1 · Waiting case · [2024] 1 REP 10",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting", { selector: ".status-chip" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View" })).toHaveAttribute(
      "href",
      expect.stringContaining("/adjudication/00000000"),
    );
    expect(
      screen.getByText("No adjudication is assigned to you for this case"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0/0 · 0%")).not.toBeInTheDocument();

    const disclosures = screen.getAllByText("Show field progress");
    await user.click(disclosures[0]);
    const openDetails = disclosures[0].closest("details");
    expect(openDetails).toHaveAttribute("open");
    expect(
      within(openDetails!).getByRole("columnheader", { name: "Reviewer progress" }),
    ).toBeInTheDocument();
    expect(within(openDetails!).getByText("2/3 reviews")).toBeInTheDocument();
    const waitingFor = within(openDetails!).getByLabelText(
      "Waiting for A reviewer with a deliberately long display name, fallback-reviewer@example.test",
    );
    expect(waitingFor).toHaveAttribute(
      "title",
      "Waiting for A reviewer with a deliberately long display name, fallback-reviewer@example.test",
    );
    expect(within(waitingFor).getByText("fallback-reviewer@example.test")).toHaveClass(
      "pending-reviewer-name",
    );
    expect(within(openDetails!).getByText("Awaiting reviews")).toBeInTheDocument();
  });
});
