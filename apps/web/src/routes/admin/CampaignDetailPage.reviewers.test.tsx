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

describe("reviewers workflows", () => {
  it("greys out and shows 0 when no eligible reviewers exist", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, { roster: { items: [], next_cursor: null } });
    renderCampaignDetail(tenantId, campaignId);

    const fieldset = await screen.findByRole("group", { name: /eligible reviewers/i });
    expect(fieldset).toHaveClass("is-disabled");
    expect(screen.getByText(/0 — no active eligible reviewers yet/i)).toBeInTheDocument();
  });

  it("highlights the reviewer box red when the allocation summary reports insufficient reviewers", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { selected_reviewer_ids: [reviewerAId] }),
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_reviewers: 1,
        feasible: false,
        infeasible_reason: "insufficient_reviewers",
        infeasible_message:
          "At least 2 reviewers are required when the number of reviews per case is 2 or more.",
      }),
    });
    renderCampaignDetail(tenantId, campaignId);

    const fieldset = await screen.findByRole("group", { name: /eligible reviewers/i });
    await waitFor(() => expect(fieldset).toHaveAttribute("aria-invalid", "true"));
    expect(fieldset).toHaveClass("is-invalid");
    expect(
      screen.getAllByText(/at least 2 reviewers are required when the number of reviews per case/i)
        .length,
    ).toBeGreaterThan(0);
  });

  it("highlights the reviewer box red when eligible reviewers exist but none are selected yet", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      allocationSummary: baseAllocationSummary(campaignId, {
        selected_reviewers: 0,
        feasible: false,
        infeasible_reason: "no_selected_reviewers",
        infeasible_message:
          "No active reviewers are selected yet. Add at least 2 before allocating.",
      }),
    });
    renderCampaignDetail(tenantId, campaignId);

    const fieldset = await screen.findByRole("group", { name: /eligible reviewers/i });
    await waitFor(() => expect(fieldset).toHaveAttribute("aria-invalid", "true"));
    expect(fieldset).toHaveClass("is-invalid");
    expect(
      screen.getAllByText(/no active reviewers are selected yet\. add at least 2/i).length,
    ).toBeGreaterThan(0);
  });

  it("adds a reviewer via the campaign reviewers endpoint", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      reviewerHandler: () =>
        jsonResponse({
          campaign_id: campaignId,
          selected_reviewer_ids: [reviewerAId],
          schema_version: "campaign-reviewers/v1",
        }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    const checkbox = await screen.findByRole("checkbox", { name: /reviewer one/i });
    await user.click(checkbox);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringMatching(new RegExp(`/campaigns/${campaignId}/reviewers$`)),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("allows deletion with a selected roster when the backend confirms no work exists", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { selected_reviewer_ids: [reviewerAId] }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await user.click(await screen.findByRole("button", { name: /^edit draft$/i }));
    const editHeading = screen.getByRole("heading", { name: /^edit campaign$/i });
    await user.click(await screen.findByRole("button", { name: /^delete campaign$/i }));
    const deleteDialog = await screen.findByRole("alertdialog", {
      name: /confirm campaign delete/i,
    });
    expect(deleteDialog).toBeInTheDocument();
    expect(
      deleteDialog.compareDocumentPosition(editHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /yes, delete this campaign/i }));
    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(
            ([input, init]) =>
              String(input).includes(`/campaigns/${campaignId}?confirm=true`) &&
              init?.method === "DELETE",
          ),
      ).toBe(true),
    );
  });

  it("shows campaign-scoped reviewer coverage including a newly selected zero-work reviewer", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        selected_reviewer_ids: [reviewerAId, reviewerBId],
      }),
      workload: [
        {
          reviewer_id: reviewerAId,
          total_assignments: 8,
          claimed_count: 5,
          submitted_count: 3,
          released_count: 0,
        },
      ],
    });
    renderCampaignDetail(tenantId, campaignId);

    const table = await screen.findByRole("table", { name: /reviewer coverage/i });
    expect(
      within(table).getByRole("row", { name: /Reviewer One Yes 8 5 3 0/i }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("row", { name: /Reviewer Two Yes 0 0 0 0/i }),
    ).toBeInTheDocument();
    expect(within(table).queryByText(reviewerAId)).not.toBeInTheDocument();
    expect(within(table).queryByText(reviewerBId)).not.toBeInTheDocument();
  });

  it("flags a reviewer who holds live assignments but was unchecked from the roster", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        // Only reviewer B is on the current roster -- reviewer A was removed from policy_json but
        // still owns a live (non-released) assignment, so they still have queue access.
        selected_reviewer_ids: [reviewerBId],
      }),
      workload: [
        {
          reviewer_id: reviewerAId,
          total_assignments: 4,
          claimed_count: 4,
          submitted_count: 0,
          released_count: 0,
        },
      ],
    });
    renderCampaignDetail(tenantId, campaignId);

    // Eligible reviewers checklist: reviewer A is unchecked but flagged as still having access.
    const checklist = await screen.findByRole("group", { name: /eligible reviewers/i });
    const reviewerARow = within(checklist)
      .getByText(/Reviewer One/i)
      .closest("label");
    expect(reviewerARow).not.toBeNull();
    expect(within(reviewerARow as HTMLElement).getByText(/has access/i)).toBeInTheDocument();
    expect(within(checklist).getByRole("checkbox", { name: /Reviewer One/i })).not.toBeChecked();

    // Reviewer coverage table: "On roster" reads a clear "no, but has access" signal.
    const table = await screen.findByRole("table", { name: /reviewer coverage/i });
    const reviewerARowInTable = within(table).getByRole("row", { name: /Reviewer One/i });
    expect(within(reviewerARowInTable).getByText(/has access/i)).toBeInTheDocument();
  });

  it("freezes the remove control with a tooltip for a reviewer who has saved or submitted work", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        selected_reviewer_ids: [reviewerAId, reviewerBId],
      }),
      workload: [
        {
          reviewer_id: reviewerAId,
          total_assignments: 1,
          claimed_count: 0,
          submitted_count: 1,
          released_count: 0,
          has_work: true,
        },
        {
          reviewer_id: reviewerBId,
          total_assignments: 1,
          claimed_count: 1,
          submitted_count: 0,
          released_count: 0,
          has_work: false,
        },
      ],
    });
    renderCampaignDetail(tenantId, campaignId);

    const frozenCheckbox = await screen.findByRole("checkbox", { name: /reviewer one/i });
    expect(frozenCheckbox).toBeDisabled();
    expect(frozenCheckbox.closest("label")).toHaveAttribute(
      "title",
      expect.stringMatching(/can't remove/i),
    );

    const freeCheckbox = await screen.findByRole("checkbox", { name: /reviewer two/i });
    expect(freeCheckbox).not.toBeDisabled();
  });

  it("previews and publishes an assignment plan for a feasible campaign with more cases than reviewers", async () => {
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
    expect(await screen.findByText(/assignment preview: ready to publish/i)).toBeInTheDocument();
    expect(screen.queryByText(/^preview feasibility:/i)).not.toBeInTheDocument();

    const previewCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/allocation-runs/preview"));
    expect(previewCall).toBeDefined();
    const previewBody = JSON.parse(String(previewCall?.[1]?.body ?? "{}")) as Record<
      string,
      unknown
    >;
    expect(previewBody.uniform_reviews_per_subject).toBe(2);
    expect(previewBody.target_pairwise_overlap).toBe(0);
    expect(previewBody.target_global_overlap).toBe(0);

    expect(screen.queryByRole("button", { name: /^persist plan$/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^publish assignments$/i }));
    expect(
      await screen.findByText(/published 24 case assignments \(120 review-unit assignments\)/i),
    ).toBeInTheDocument();

    const publishCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/allocation-runs/publish"));
    expect(publishCall).toBeDefined();
  });

  it("shows a cases-fully-complete progress bar distinct from the reviewer-slot progress bar", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      progress: {
        cases_total: 10,
        reviewers_total: 2,
        total_assignments: 4,
        case_reviewer_slots_total: 20,
        case_reviewer_completions: 2,
        cases_fully_complete_count: 1,
      },
    });
    renderCampaignDetail(tenantId, campaignId);

    expect(await screen.findByText(/cases fully complete/i)).toBeInTheDocument();
    expect(await screen.findByText(/1\/10/i)).toBeInTheDocument();
    // The reviewer-slot progress bar remains its own distinct metric (2/20), not conflated with
    // the 1/10 fully-complete-cases count above.
    expect(await screen.findByText(/cases reviewed, by reviewer/i)).toBeInTheDocument();
    expect(await screen.findByText(/2\/20/i)).toBeInTheDocument();
  });

  it("shows the cases-by-reviewer progress bar once a campaign has reviewer slots", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      progress: {
        cases_total: 8,
        reviewers_total: 2,
        total_assignments: 4,
        case_reviewer_slots_total: 16,
        case_reviewer_completions: 3,
      },
    });
    renderCampaignDetail(tenantId, campaignId);

    expect(await screen.findByText(/cases reviewed, by reviewer/i)).toBeInTheDocument();
    expect(await screen.findByText(/3\/16/i)).toBeInTheDocument();
    expect(screen.getByText(/19%/i)).toBeInTheDocument();
  });
});
