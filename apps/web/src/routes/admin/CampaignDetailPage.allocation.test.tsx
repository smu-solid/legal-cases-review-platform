import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  baseAllocationSummary,
  baseCampaign,
  freshIds,
  mockCampaignDetailApi,
  renderCampaignDetail,
  reviewerAId,
  reviewerBId,
} from "../../test/campaignScenarios";

describe("allocation workflows", () => {
  it("names both assignment granularities so the panel, preview and publish agree", async () => {
    // The pre-publish panel used to report "Total reviewer assignments" case-level (cases x
    // reviews per case) while the publish result reported the fanned-out unit count, both labelled
    // only "assignments" -- so one campaign read as 24 in one place and 120 in another. Every
    // surface must now name which granularity it means, and show both, case level first.
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { selected_reviewer_ids: [reviewerAId, reviewerBId] }),
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_reviewers: 2,
        feasible: true,
        infeasible_reason: null,
        infeasible_message: null,
        estimated_assignments_per_reviewer: 12,
      }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    // Panel: both figures present, each under its own name, and no bare "Total reviewer
    // assignments" label that says nothing about which one it is.
    const caseMetric = (await screen.findByText(/^case assignments$/i)).closest(".metric-card");
    expect(caseMetric).not.toBeNull();
    expect(within(caseMetric as HTMLElement).getByText("24")).toBeInTheDocument();
    const unitMetric = screen.getAllByText(/^review-unit assignments$/i)[0].closest(".metric-card");
    expect(unitMetric).not.toBeNull();
    expect(within(unitMetric as HTMLElement).getByText("120")).toBeInTheDocument();
    expect(screen.queryByText(/total reviewer assignments/i)).not.toBeInTheDocument();

    // Preview quotes the same pair...
    await user.click(await screen.findByRole("button", { name: /^preview assignment plan$/i }));
    expect(
      await screen.findByText(/plans 24 case assignments \(120 review-unit assignments\)/i),
    ).toBeInTheDocument();

    // ...and publish reports exactly what the preview promised, in the same words.
    await user.click(screen.getByRole("button", { name: /^publish assignments$/i }));
    expect(
      await screen.findByText(/published 24 case assignments \(120 review-unit assignments\)/i),
    ).toBeInTheDocument();
  });

  it("blocks publishing and explains why when the real preview disagrees with the pre-preview estimate", async () => {
    // The pre-preview estimate only counts *selected* reviewer ids, not their live active/authorized
    // status, so it can say "feasible" while the real allocation engine correctly returns
    // blocked_by_reviewer_pool (e.g. a selected reviewer was deactivated server-side). Publish must
    // not be enabled just because a preview happened -- it must check the preview's own feasibility.
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { selected_reviewer_ids: [reviewerAId, reviewerBId] }),
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_reviewers: 2,
        feasible: true,
        infeasible_reason: null,
        infeasible_message: null,
        estimated_assignments_per_reviewer: 12,
      }),
      allocationPreview: {
        feasibility: {
          status: "blocked_by_reviewer_pool",
          errors: [
            {
              code: "blocked_by_reviewer_pool",
              message: "1 reviewer(s) are inactive or unauthorized.",
            },
          ],
          warnings: [],
          computed_totals: {},
          suggested_adjustments: [],
        },
        reviewer_workloads: [],
      },
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await user.click(await screen.findByRole("button", { name: /^preview assignment plan$/i }));
    expect(await screen.findByText(/assignment preview: add more reviewers/i)).toBeInTheDocument();
    expect(screen.getByText(/1 reviewer\(s\) are inactive or unauthorized\./i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^publish assignments$/i })).toBeDisabled();
  });

  it("disables allocation actions and explains why when the campaign has 0 review units", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_cases: 0,
        total_assignments: 0,
        feasible: false,
        infeasible_reason: "no_selected_cases",
        infeasible_message: "No cases are selected for this campaign yet.",
      }),
    });
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Assignment plan" });
    expect(screen.getByText(/no cases or fields are in this campaign/i)).toHaveClass("form-error");
    expect(screen.getByRole("button", { name: /^preview assignment plan$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^publish assignments$/i })).toBeDisabled();
  });
});
