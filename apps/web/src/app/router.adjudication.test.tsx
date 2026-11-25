import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  adjudicationId,
  adminMe,
  mockAdjudicationQueueApi,
  mockAdjudicationQueueErrorApi,
  mockAdjudicationWorkspaceApi,
  mockReviewerStagingApi,
  renderAt,
  reviewerWorkspaceTenantId,
  tenantId,
} from "../test/routerScenarios";
import { queryClient } from "./queryClient";

describe("adjudication workflows", () => {
  it("shows a clean empty state for an authorized adjudication queue", async () => {
    mockAdjudicationQueueApi(adminMe, []);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(
      await screen.findByRole("heading", { name: /no adjudication campaigns/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/adjudication queue could not be loaded/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not authorized to adjudicate/i)).not.toBeInTheDocument();
  });

  it("renders campaign status counts and progress before case selection", async () => {
    mockAdjudicationQueueApi(adminMe, [
      {
        campaign_id: "00000000-0000-4000-8000-000000000050",
        campaign_key: "adjudication-campaign",
        campaign_name: "Adjudication campaign",
        waiting_count: 1,
        in_progress_count: 2,
        finished_count: 3,
        not_required_count: 1,
        total_case_count: 6,
      },
    ]);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(
      await screen.findByRole("heading", { name: "Adjudication campaign" }),
    ).toBeInTheDocument();
    expect(screen.getByText("3/6 · 50%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View cases" })).toHaveAttribute(
      "href",
      `/t/${tenantId}/adjudication/campaigns/00000000-0000-4000-8000-000000000050`,
    );
  });

  it("shows campaigns that currently contain only waiting cases", async () => {
    mockAdjudicationQueueApi(adminMe, [
      {
        campaign_id: "00000000-0000-4000-8000-000000000050",
        campaign_key: "waiting-campaign",
        campaign_name: "Adjudication campaign",
        waiting_count: 1,
        in_progress_count: 0,
        finished_count: 0,
        not_required_count: 0,
        total_case_count: 1,
      },
    ]);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(await screen.findByText("0/1 · 0%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View cases" })).toBeInTheDocument();
  });

  it("shows an authorization notice for an adjudication queue 403 without a request loop", async () => {
    mockAdjudicationQueueErrorApi(adminMe, 403);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(
      await screen.findByText(/you are not authorized to adjudicate for this tenant/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/adjudication queue could not be loaded/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /no adjudications available/i }),
    ).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/review/adjudication-campaigns")),
    ).toHaveLength(1);
  });

  it("shows adjudication unavailable only for a true queue failure", async () => {
    mockAdjudicationQueueErrorApi(adminMe, 503);
    renderAt(`/t/${tenantId}/adjudication`);

    expect(
      await screen.findByText(/adjudication campaigns could not be loaded/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/not authorized to adjudicate/i)).not.toBeInTheDocument();
  });

  it("shows reviewer identities only inside the authorized adjudication workspace", async () => {
    mockAdjudicationWorkspaceApi(adminMe);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);

    expect(
      await screen.findByRole("heading", {
        name: "[2017] SGHC 12 · Adjudication subject alpha · [2017] 4 REP 3",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Your campaign")).toBeInTheDocument();
    expect(screen.getByLabelText("Case submit progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shortcuts (?)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review & submit case" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to campaign cases/i })).toBeInTheDocument();
    expect(await screen.findByText("Aisha Rahman")).toBeInTheDocument();
    expect(screen.getByText("fallback-reviewer@example.test")).toBeInTheDocument();
    expect(screen.getByText("Ben Tan")).toBeInTheDocument();
    expect(screen.getByText(/aisha rahman preferred/i)).toBeInTheDocument();
    expect(screen.getByText(/fallback-reviewer@example\.test preferred/i)).toBeInTheDocument();
    expect(screen.getByText(/ben tan preferred/i)).toBeInTheDocument();
    expect(screen.getByText(/all equivalent \/ supported/i)).toBeInTheDocument();
    expect(screen.getByText(/^all wrong$/i)).toBeInTheDocument();
    expect(screen.queryByText(/candidate a assessment/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(7);
    const allWrong = screen.getByRole("radio", { name: /^all wrong$/i });
    expect(allWrong).not.toBeChecked();
    await user.click(allWrong);
    expect(allWrong).toBeChecked();
    expect(screen.getByRole("button", { name: /citations 1\/2/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/agreement status/i)).toHaveValue("all");
    await user.click(screen.getByRole("button", { name: /reported citation/i }));
    expect(await screen.findByText("Chloe Lim")).toBeInTheDocument();
    expect(screen.queryByText(/reviewer identities are hidden/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin@local\.test/i)).not.toBeInTheDocument();
  });

  it("shares source controls and highlights selected fields plus reviewer-corrected provenance", async () => {
    mockAdjudicationWorkspaceApi(adminMe);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);

    await screen.findByRole("button", { name: /neutral citation/i });
    const source = document.querySelector(".adjudication-source-pane .source-text");
    expect(source?.textContent).toBe("[2017] SGHC 12\nReported [2017] 4 REP 3");
    expect(await screen.findByRole("group", { name: /source view mode/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Judgment" })).toBeVisible();
    expect(screen.queryByText("Sample A")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand source view/i })).toBeInTheDocument();
    expect(
      Array.from(source?.querySelectorAll('[data-active-anchor="true"]') ?? [])
        .map((node) => node.textContent)
        .join(""),
    ).toBe("[2017] SGHC 12");
    expect(source?.querySelector(".source-highlight-selected")?.textContent).toBe("[2017] ");
    expect(
      source?.querySelector(".source-highlight-selected")?.getAttribute("data-highlight-owners"),
    ).toBe("Highlighted by: Aisha Rahman");
    const reviewerOverlap = source?.querySelector(".source-highlight-reviewer-overlap");
    expect(reviewerOverlap?.textContent).toBe("SGHC 12");
    expect(reviewerOverlap?.getAttribute("data-highlight-owners")).toBe(
      "Highlighted by: Aisha Rahman, fallback-reviewer@example.test",
    );
    fireEvent.mouseEnter(reviewerOverlap as Element, { clientX: 200, clientY: 200 });
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Highlighted by: Aisha Rahman, fallback-reviewer@example.test",
    );
    fireEvent.mouseLeave(reviewerOverlap as Element);
    expect(screen.getAllByText("Evidence points to the wrong place")).toHaveLength(2);
    expect(screen.getAllByText("Reviewer marked provenance")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Document" }));
    expect(await screen.findByTitle(/sanitized source document/i)).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("Sanitized adjudication document"),
    );
    await user.click(screen.getByRole("button", { name: "Text" }));

    await user.click(screen.getByRole("button", { name: /reported citation/i }));
    await waitFor(() =>
      expect(
        document.querySelector('.adjudication-source-pane .source-text [data-active-anchor="true"]')
          ?.textContent,
      ).toBe("[2017] 4 REP 3"),
    );
    expect(
      document.querySelector(".adjudication-source-pane .source-highlight-adjudicator")
        ?.textContent,
    ).toBe("[2017] 4 REP 3");
    expect(
      document
        .querySelector(".adjudication-source-pane .source-highlight-adjudicator")
        ?.getAttribute("data-highlight-owners"),
    ).toBe("Highlighted by: Admin Local");
    expect(screen.getByLabelText(/adjudicator note/i)).toHaveValue("Final read-only note");
    expect(screen.getByText("This finished adjudication is read-only.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit adjudication/i })).not.toBeInTheDocument();
  });

  it("filters fields by agreement status and keeps the filter available in an empty state", async () => {
    mockAdjudicationWorkspaceApi(adminMe);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);

    const filter = await screen.findByLabelText(/agreement status/i);
    expect(filter).toHaveValue("all");
    expect(screen.getByRole("option", { name: /value\/provenance disagreement/i })).toHaveValue(
      "value_provenance_disagreement",
    );
    expect(await screen.findByRole("button", { name: /neutral citation/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /reported citation/i })).toBeInTheDocument();

    await user.selectOptions(filter, "disagreement");
    expect(await screen.findByRole("button", { name: /neutral citation/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reported citation/i })).not.toBeInTheDocument();

    await user.selectOptions(filter, "positive_agreement");
    expect(await screen.findByText(/no fields match this filter/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/agreement status/i)).toBeInTheDocument();

    await user.selectOptions(filter, "all");
    expect(await screen.findByRole("button", { name: /neutral citation/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /reported citation/i })).toBeInTheDocument();
  });

  it("saves and reloads a private note before a verdict without enabling final submission", async () => {
    mockAdjudicationWorkspaceApi(adminMe, true);
    const user = userEvent.setup();
    const path = `/t/${tenantId}/adjudication/${adjudicationId}`;
    renderAt(path);
    const note = await screen.findByLabelText(/adjudicator note/i);
    expect(note).toBeEnabled();
    expect(screen.getByRole("button", { name: /save draft/i })).toBeDisabled();
    await user.type(note, "Private note before a verdict");
    expect(screen.getByRole("button", { name: /submit adjudication/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /save draft/i }));
    expect(await screen.findByText(/draft saved/i)).toBeInTheDocument();
    const draftCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(
        ([input, init]) => String(input).endsWith("/draft") && init?.method === "PUT",
      );
    expect(JSON.parse(String(draftCall?.[1]?.body))).toMatchObject({
      outcome: null,
      comment: "Private note before a verdict",
      reviewer_assessments: [],
    });
    cleanup();
    queryClient.clear();
    renderAt(path);
    expect(await screen.findByLabelText(/adjudicator note/i)).toHaveValue(
      "Private note before a verdict",
    );
    expect(screen.getByRole("button", { name: /submit adjudication/i })).toBeDisabled();
    expect(
      screen.getAllByRole("radio").every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
  });

  it("retains the leave guard and saves a note-only draft before continuing to the next case", async () => {
    mockAdjudicationWorkspaceApi(adminMe, true);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);
    await user.type(await screen.findByLabelText(/adjudicator note/i), "Save before navigating");
    await user.click(screen.getByRole("button", { name: /next case/i }));
    const leaveDialog = await screen.findByRole("dialog", {
      name: "Save your drafts before leaving",
    });
    expect(within(leaveDialog).getByRole("button", { name: "Stay and edit" })).toBeEnabled();
    await user.click(within(leaveDialog).getByRole("button", { name: "Save drafts and leave" }));
    await waitFor(() => {
      const draftCall = vi
        .mocked(globalThis.fetch)
        .mock.calls.find(
          ([input, init]) => String(input).endsWith("/draft") && init?.method === "PUT",
        );
      expect(JSON.parse(String(draftCall?.[1]?.body))).toMatchObject({
        outcome: null,
        comment: "Save before navigating",
      });
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(([input]) =>
            String(input).includes("/00000000-0000-4000-8000-000000000044/case-workspace"),
          ),
      ).toBe(true);
    });
  });

  it("saves an adjudication draft and stays in the workspace until every case field is resolved", async () => {
    mockAdjudicationWorkspaceApi(adminMe, true);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);

    await screen.findByRole("button", { name: /neutral citation/i });
    await user.click(screen.getByText(/all equivalent \/ supported/i));
    await user.type(screen.getByLabelText(/adjudicator note/i), "Draft note");
    await user.click(screen.getByRole("button", { name: /save draft/i }));
    expect(await screen.findByText(/draft saved/i)).toBeInTheDocument();
    const draftCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(
        ([input, init]) => String(input).endsWith("/draft") && init?.method === "PUT",
      );
    expect(JSON.parse(String(draftCall?.[1]?.body))).toMatchObject({ comment: "Draft note" });

    await user.click(screen.getByRole("button", { name: /submit adjudication/i }));
    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(([input]) =>
            String(input).includes(`/review/adjudications/${adjudicationId}/case-workspace`),
          ),
      ).toBe(true),
    );
    expect(await screen.findByLabelText(/agreement status/i)).toHaveValue("all");
    expect(screen.getByRole("button", { name: /reported citation/i })).toHaveClass("is-active");
    expect(
      screen.queryByRole("heading", { name: /^adjudication campaigns$/i }),
    ).not.toBeInTheDocument();
  });

  it("stays on a read-only completion state when the submitted field completes the case", async () => {
    mockAdjudicationWorkspaceApi(adminMe, false);
    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/adjudication/${adjudicationId}`);

    await screen.findByRole("button", { name: /neutral citation/i });
    await user.click(screen.getByText(/all equivalent \/ supported/i));
    await user.click(screen.getByRole("button", { name: /submit adjudication/i }));

    expect(await screen.findByText(/case adjudication complete/i)).toBeInTheDocument();
    expect(screen.getByText(/submitted decisions are read-only/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^campaign cases$/i })).toHaveClass("primary-button");
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.some(([input]) => String(input).includes(`${adjudicationId}/case-workspace`)),
    ).toBe(true);
  });

  it("runs the reviewer local staging workspace through source render, draft, and submit", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review`);

    expect(
      await screen.findByRole("heading", { name: /your assigned campaigns/i }),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /open campaign queue/i }));
    expect(
      await screen.findByRole("heading", { name: /reviewer staging campaign/i }),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /^show fields$/i }));
    await user.click(await screen.findByRole("button", { name: /^open task$/i }));

    expect(
      await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i }),
    ).toBeInTheDocument();
    // Text is the default view: its anchor offsets are exact by construction, unlike Document's
    // search-matched artifact anchors (see ReviewerWorkspacePage.tsx's sourceView default).
    expect(await screen.findByText(/Review Platform synthetic source/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^document$/i }));
    expect(
      await screen.findByTitle(/sanitized source document for public prosecutor v tan wei ming/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^text$/i }));

    const yesButtons = screen.getAllByRole("button", { name: /^yes$/i });
    await user.click(yesButtons[0]);
    await user.click(yesButtons[1]);
    await user.click(screen.getByRole("button", { name: /^save draft$/i }));
    expect((await screen.findAllByText(/^draft saved$/i)).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /^submit field$/i }));
    // The nav card's title attribute carries the real per-item status once the compact nav no
    // longer shows a visible "Submitted" legend; the active pane may already have advanced to the
    // next field by this point.
    expect(await screen.findByTitle(/— submitted$/i)).toBeInTheDocument();

    const requestedUrls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/\/review\/queue\?/),
        expect.stringMatching(/\/review\/assignments\/.*\/grouped-bundle$/),
        expect.stringMatching(/\/review\/assignments\/.*\/source-render$/),
        expect.stringMatching(/\/review\/assignments\/.*\/source-render\/body$/),
        expect.stringMatching(/\/review\/assignments\/.*\/source-render\/anchors$/),
        expect.stringMatching(/\/review\/assignments\/.*\/answer\/draft$/),
        expect.stringMatching(/\/review\/assignments\/.*\/answer\/submit$/),
      ]),
    );
    expect(requestedUrls.some((url) => url.includes("/admin/"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/adjudication"))).toBe(false);
  });
});
