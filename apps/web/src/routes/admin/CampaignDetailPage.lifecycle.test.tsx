import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  baseAllocationSummary,
  baseCampaign,
  freshIds,
  jsonResponse,
  mockCampaignDetailApi,
  renderCampaignDetail,
  reviewerAId,
  reviewerBId,
} from "../../test/campaignScenarios";

describe("lifecycle workflows", () => {
  it("renders campaign name, key, and status from the backend detail endpoint", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId);
    renderCampaignDetail(tenantId, campaignId);

    expect(
      await screen.findByRole("heading", { name: "Local staging campaign" }),
    ).toBeInTheDocument();
    expect(screen.getByText("local-staging")).toBeInTheDocument();
  });

  it("builds the page from the shared responsive admin layout primitives", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId);
    const { container } = renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(container.querySelector(".admin-page")).toBeInTheDocument();
    expect(container.querySelectorAll(".admin-card").length).toBeGreaterThan(0);
    expect(container.querySelector(".admin-metric-grid")).toBeInTheDocument();
    expect(container.querySelector(".page-panel")).not.toBeInTheDocument();
  });

  it("marks a published campaign completed and shows the Completed badge", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { status: "published" }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await user.click(await screen.findByRole("button", { name: /^mark completed$/i }));
    expect(
      await screen.findByRole("alertdialog", { name: /confirm mark campaign completed/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /yes, mark completed/i }));

    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(
            ([input, init]) =>
              String(input).endsWith(`/campaigns/${campaignId}/complete`) &&
              init?.method === "POST",
          ),
      ).toBe(true),
    );

    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^mark completed$/i })).not.toBeInTheDocument();
  });

  it("does not offer Mark completed for a draft campaign", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, { campaign: baseCampaign(campaignId) });
    renderCampaignDetail(tenantId, campaignId);
    await screen.findByText(/local staging campaign/i);
    expect(screen.queryByRole("button", { name: /^mark completed$/i })).not.toBeInTheDocument();
  });

  it("does not offer Mark completed again once a published campaign is already completed", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { status: "published", completed: true }),
    });
    renderCampaignDetail(tenantId, campaignId);
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^mark completed$/i })).not.toBeInTheDocument();
  });

  it("hides the delete action for a closed campaign and explains that it cannot reopen", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { status: "closed" }),
    });
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(screen.queryByRole("button", { name: /^delete campaign$/i })).not.toBeInTheDocument();
    expect(screen.getByText(/closed and cannot be reopened/i)).toBeInTheDocument();
  });

  it("does not confirm when only non-source campaign details changed", async () => {
    const { tenantId, campaignId } = freshIds();
    let confirmedEdit = false;
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { selected_reviewer_ids: [reviewerAId, reviewerBId] }),
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_reviewers: 2,
        feasible: true,
        infeasible_reason: null,
      }),
      editHandler: (body) => {
        expect(body.confirm).toBe(false);
        expect(body).not.toHaveProperty("reviews_per_case");
        confirmedEdit = true;
        return jsonResponse(
          baseCampaign(campaignId, {
            selected_reviewer_ids: [reviewerAId, reviewerBId],
            campaign_name: "Renamed campaign",
          }),
        );
      },
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await user.click(await screen.findByRole("button", { name: /^edit draft$/i }));
    const nameInput = await screen.findByLabelText(/^campaign name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed campaign");
    await user.click(screen.getByRole("button", { name: /^save changes$/i }));

    await waitFor(() => expect(confirmedEdit).toBe(true));
    expect(screen.queryByRole("alertdialog", { name: /confirm campaign edit/i })).toBeNull();
  });

  it("refetches campaign monitor data after publish instead of leaving it stale", async () => {
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

    await user.click(await screen.findByRole("button", { name: /^preview assignment plan$/i }));
    await screen.findByText(/assignment preview: ready to publish/i);

    const progressCallsBeforePublish = vi
      .mocked(globalThis.fetch)
      .mock.calls.filter(([input]) => String(input).includes("/review/campaign-progress")).length;
    expect(progressCallsBeforePublish).toBeGreaterThan(0);
    const workloadCallsBeforePublish = vi
      .mocked(globalThis.fetch)
      .mock.calls.filter(([input]) => String(input).includes("/review/reviewer-workload")).length;
    expect(workloadCallsBeforePublish).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /^publish assignments$/i }));
    await screen.findByText(/published 24 case assignments \(120 review-unit assignments\)/i);

    await waitFor(() => {
      const progressCallsAfterPublish = vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/review/campaign-progress")).length;
      expect(progressCallsAfterPublish).toBeGreaterThan(progressCallsBeforePublish);
      const workloadCallsAfterPublish = vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/review/reviewer-workload")).length;
      expect(workloadCallsAfterPublish).toBeGreaterThan(workloadCallsBeforePublish);
    });
  });

  it("renders the paginated per-case table", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      cases: [
        {
          case_id: "CAS-000501",
          display_title: "Case Alpha",
          review_kinds: ["metadata_field"],
          field_group_labels: ["Case metadata"],
          unit_count: 1,
          assignment_count: 2,
          submitted_count: 1,
          reviewers_assigned_count: 2,
          reviewers_completed_count: 1,
          resolved_count: 0,
        },
      ],
    });
    renderCampaignDetail(tenantId, campaignId);

    expect(await screen.findByText("Case Alpha")).toBeInTheDocument();
    expect(
      await screen.findByRole("row", { name: /Case Alpha Case metadata 1 2 1 1\/2 0/i }),
    ).toBeInTheDocument();
    // The raw internal token must never reach the primary UI -- only the human label.
    expect(screen.queryByText("metadata_field")).not.toBeInTheDocument();
  });

  it("refreshes selector counts, progress, and per-case rows after adding cases", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        case_filter: {
          version: "v1",
          all: [{ field_id: "case_subject", operator: "contains_ci", value: "Criminal" }],
        },
      }),
      afterPoolCases: {
        allocationSummary: { selected_cases: 17, review_units: 65 },
        progress: { cases_total: 17, total_units: 65 },
        availability: {
          eligible_cases_count: 1,
          source_pool_cases_count: 4,
          case_filter_matching_count: 1,
          projected_campaign_cases_count: 1,
        },
        cases: [
          {
            case_id: "CAS-NEW",
            display_title: "Newly added case",
            review_kinds: ["metadata_field"],
            field_group_labels: ["Case metadata"],
            unit_count: 5,
            assignment_count: 0,
            submitted_count: 0,
            reviewers_assigned_count: 0,
            reviewers_completed_count: 0,
            resolved_count: 0,
          },
        ],
      },
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    const addCasesCard = (
      await screen.findByRole("heading", { name: /add cases from preloaded pool/i })
    ).closest("section");
    expect(addCasesCard).not.toBeNull();
    expect(
      await within(addCasesCard as HTMLElement).findByRole("button", { name: /^add 3 cases$/i }),
    ).toBeEnabled();
    const caseCallsBefore = vi
      .mocked(globalThis.fetch)
      .mock.calls.filter(([input]) =>
        String(input).includes(`/campaigns/${campaignId}/cases`),
      ).length;
    const progressCallsBefore = vi
      .mocked(globalThis.fetch)
      .mock.calls.filter(([input]) => String(input).includes("/review/campaign-progress")).length;

    await user.click(
      within(addCasesCard as HTMLElement).getByRole("button", { name: /^add 3 cases$/i }),
    );

    expect(
      await within(addCasesCard as HTMLElement).findByRole("button", { name: /^add 1 case$/i }),
    ).toBeEnabled();
    expect(await screen.findByText("Newly added case")).toBeInTheDocument();
    expect(await screen.findByText("0/17 · 0%")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => String(input).includes(`/campaigns/${campaignId}/cases`))
          .length,
      ).toBeGreaterThan(caseCallsBefore);
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => String(input).includes("/review/campaign-progress"))
          .length,
      ).toBeGreaterThan(progressCallsBefore);
    });
  });

  it("keeps reviews per case frozen while editing a draft campaign", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { status: "draft", reviews_per_case: 3 }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    const reviewsPerCase = await screen.findByLabelText(/^number of reviews per case$/i);
    const campaignFields = reviewsPerCase.closest(".campaign-edit-field");
    expect(reviewsPerCase).toHaveValue(3);
    expect(reviewsPerCase).toBeDisabled();
    expect(reviewsPerCase).toHaveClass("frozen-input");
    expect(campaignFields).toHaveClass("is-disabled");

    await user.click(screen.getByRole("button", { name: /^edit draft$/i }));

    expect(reviewsPerCase).toHaveValue(3);
    expect(reviewsPerCase).toBeDisabled();
    expect(campaignFields).not.toHaveClass("is-disabled");
  });

  it("collapses the monitor panel to a calm empty state for a draft campaign with cases but no published assignments", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId);
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Campaign progress" });
    expect(
      screen.getByText(/cases loaded\. publish assignments to begin monitoring/i),
    ).toBeInTheDocument();
  });

  it("collapses the monitor panel to a calm empty state for a draft campaign with 0 cases", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      progress: { cases_total: 0, total_units: 0 },
    });
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Campaign progress" });
    expect(
      screen.getByText(/monitoring starts after cases are loaded and assignments are published/i),
    ).toBeInTheDocument();
  });
});
