import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  baseCampaign,
  freshIds,
  mockCampaignDetailApi,
  renderCampaignDetail,
} from "../../test/campaignScenarios";

describe("selection workflows", () => {
  it("loads more cases from the pool into a draft campaign via the pool-cases endpoint", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId);
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(await screen.findByText("17 cases")).toBeInTheDocument();
    expect(screen.getByText("12 cases")).toBeInTheDocument();
    expect(screen.getAllByText("5 cases")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /^add 5 cases$/i }));

    expect(await screen.findByText(/added 5 cases \(5 review units\)/i)).toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/review\/campaigns\/.*\/pool-cases$/),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows the retained filter read-only until edit is enabled", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        case_filter: {
          version: "v1",
          all: [
            {
              field_id: "case_subject",
              operator: "contains_ci",
              value: "Criminal",
            },
          ],
        },
      }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    const addCasesCard = (
      await screen.findByRole("heading", {
        name: /add cases from preloaded pool/i,
      })
    ).closest("section");
    expect(addCasesCard).not.toBeNull();
    for (const label of [
      "Current campaign",
      "Available in pool",
      "Matches case selection",
      "Eligible to add",
      "After this add",
    ]) {
      expect(within(addCasesCard as HTMLElement).getByText(label)).toBeVisible();
    }
    expect(await screen.findByRole("button", { name: /^add 3 cases$/i })).toBeEnabled();
    const savedFilterPanel = screen.getByRole("group", { name: /filter cases/i });
    expect(savedFilterPanel).toBeDisabled();
    expect(screen.getByDisplayValue("Criminal")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^edit draft$/i }));
    expect(screen.getByDisplayValue("Criminal")).toBeEnabled();
    expect(screen.queryByDisplayValue("Civil")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^cancel edit$/i }));

    expect(screen.getByDisplayValue("Criminal")).toBeDisabled();
    expect(screen.queryByDisplayValue("Civil")).not.toBeInTheDocument();
  });

  it("applies a case filter to future top-ups without changing existing campaign cases", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId);
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(screen.getByRole("group", { name: /filter cases/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /^edit draft$/i }));
    const editCampaignCard = screen
      .getByRole("heading", { name: /^edit campaign$/i })
      .closest("section");
    expect(editCampaignCard).not.toBeNull();
    const filterPanel = within(editCampaignCard as HTMLElement).getByRole("group", {
      name: /filter cases/i,
    });
    await user.click(within(filterPanel).getByRole("button", { name: /add filter/i }));
    expect(
      within(filterPanel).getByText(/existing campaign cases remain unchanged/i),
    ).toBeInTheDocument();
    await user.selectOptions(within(filterPanel).getByLabelText("Field"), "judgment_year");
    await user.type(
      within(filterPanel).getByPlaceholderText("e.g. 2010, 2014, 2016-2019"),
      "2010, 2014, 2016-2019",
    );
    await user.click(within(filterPanel).getByRole("button", { name: /apply filters/i }));

    expect(await within(filterPanel).findByText(/3 cases in the pool/i)).toBeVisible();
    const addCasesCard = screen
      .getByRole("heading", { name: /add cases from preloaded pool/i })
      .closest("section");
    expect(addCasesCard).not.toBeNull();
    expect(within(addCasesCard as HTMLElement).getAllByText("5 cases")).toHaveLength(3);
    expect(screen.getByRole("button", { name: /^add 5 cases$/i })).toBeDisabled();
    await user.click(
      within(editCampaignCard as HTMLElement).getByRole("button", { name: /save changes/i }),
    );
    const confirmation = await screen.findByRole("alertdialog", {
      name: /confirm campaign edit/i,
    });
    expect(confirmation).toHaveTextContent(/changed the case filters or uploaded file/i);
    await user.click(within(confirmation).getByRole("button", { name: /yes, apply the edit/i }));
    await waitFor(() => {
      expect(screen.getByRole("group", { name: /filter cases/i })).toBeDisabled();
    });
    expect(screen.getByDisplayValue("2010, 2014, 2016-2019")).toBeDisabled();

    const editCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(
        ([input, init]) =>
          String(input).endsWith(`/campaigns/${campaignId}`) && init?.method === "PATCH",
      );
    expect(JSON.parse(String(editCall?.[1]?.body ?? "{}"))).toMatchObject({
      applied_filter_token: "test-filter-token",
      case_filter: {
        all: [
          {
            field_id: "judgment_year",
            operator: "in_ranges",
          },
        ],
      },
    });

    await user.click(screen.getByRole("button", { name: /^edit draft$/i }));
    expect(screen.getByDisplayValue("2010, 2014, 2016-2019")).toBeEnabled();
    await user.click(screen.getByRole("button", { name: /^cancel edit$/i }));
    await user.click(await screen.findByRole("button", { name: /^add 3 cases$/i }));

    const topUpCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith(`/campaigns/${campaignId}/pool-cases`));
    const body = JSON.parse(String(topUpCall?.[1]?.body ?? "{}")) as Record<string, unknown>;
    expect(body).not.toHaveProperty("case_filter");
    expect(body).not.toHaveProperty("applied_filter_token");
  });

  it("shows the most recent uploaded filename and selection in view and edit modes", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        case_filter: { version: "v1", all: [] },
        case_id_selection: { version: "v1", case_ids: ["CASE-1", "CASE-2"] },
        case_id_selection_file_name: "campaign-case-ids.txt",
      }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(screen.getByRole("tab", { name: /upload case ids/i })).toBeDisabled();
    expect(screen.getByRole("tab", { name: /upload case ids/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getAllByText("campaign-case-ids.txt").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unique uploaded case ids match/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/case ids not matched in the pool/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^edit draft$/i }));
    expect(screen.getByRole("tab", { name: /upload case ids/i })).toBeEnabled();
    expect(screen.getByRole("group", { name: /upload case ids/i })).toBeEnabled();
    expect(screen.getAllByText("campaign-case-ids.txt").length).toBeGreaterThan(0);
    expect(await screen.findByText(/unique uploaded case ids match/i)).toBeInTheDocument();
    expect(screen.queryByText(/case ids not matched in the pool/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/drag and drop a \.txt file here/i)).toHaveValue("");
    expect(screen.getByRole("button", { name: /save changes/i })).toBeEnabled();
  });

  it("keeps the load-cases panel available for a published campaign", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, { status: "published" }),
    });
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(
      screen.getByRole("heading", { name: /^add cases from preloaded pool$/i }),
    ).toBeInTheDocument();
  });

  it("allows a published campaign to enter the same edit flow used to select top-up cases", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      campaign: baseCampaign(campaignId, {
        status: "published",
        case_filter: {
          version: "v1",
          all: [{ field_id: "case_subject", operator: "contains_ci", value: "Employment" }],
        },
      }),
    });
    const user = userEvent.setup();
    renderCampaignDetail(tenantId, campaignId);

    expect(await screen.findByDisplayValue("Employment")).toBeDisabled();
    const campaignFields = screen
      .getByLabelText(/^campaign name$/i)
      .closest(".campaign-edit-field");
    expect(campaignFields).toHaveClass("is-disabled");

    await user.click(await screen.findByRole("button", { name: /^edit campaign$/i }));

    expect(campaignFields).not.toHaveClass("is-disabled");
    expect(screen.getByLabelText(/^campaign name$/i)).toBeEnabled();
    expect(screen.getByLabelText(/^number of reviews per case$/i)).toBeDisabled();
    expect(screen.getByRole("tab", { name: /^filter$/i })).toBeEnabled();
    expect(screen.getByRole("tab", { name: /upload case ids/i })).toBeEnabled();
    expect(screen.getByDisplayValue("Employment")).toBeEnabled();
    expect(screen.getByRole("button", { name: /^save changes$/i })).toBeEnabled();
  });

  it("explains why 0 cases are eligible instead of showing a bare zero", async () => {
    const { tenantId, campaignId } = freshIds();
    mockCampaignDetailApi(tenantId, campaignId, {
      availability: {
        eligible_cases_count: 0,
        eligible_review_units_count: 0,
        cases_available_for_all_selected_fields: 0,
        feasibility: "infeasible_no_cases",
        infeasible_message: "No eligible cases are available for this source/field scope.",
      },
    });
    renderCampaignDetail(tenantId, campaignId);

    await screen.findByRole("heading", { name: "Local staging campaign" });
    expect(await screen.findByText(/no eligible cases are available/i)).toHaveClass("form-error");
    expect(screen.getByText(/source\/field scope/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^add \d+ cases?$/i })).not.toBeInTheDocument();
  });
});
