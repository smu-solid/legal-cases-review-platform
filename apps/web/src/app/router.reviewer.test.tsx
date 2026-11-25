import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ReviewerGroupingBundle } from "../api/types";
import { syntheticBundle } from "../test/fixtures/reviewer";
import {
  answerCurrentFieldYes,
  jsonResponse,
  mockAllFieldsSubmitted,
  mockReadyCaseWithNav,
  mockReviewerQueueErrorApi,
  mockReviewerQueueWithItems,
  mockReviewerStagingApi,
  mockWorkspaceWrites,
  renderAt,
  reviewerCampaignId,
  reviewerFailureTenantId,
  reviewerMe,
  reviewerWorkspaceMe,
  reviewerWorkspaceTenantId,
  tenantId,
} from "../test/routerScenarios";

describe("reviewer workflows", () => {
  it("renders a case-grouped assigned case alongside claimable queue work", async () => {
    mockReviewerQueueWithItems();
    renderAt(`/t/${tenantId}/review/campaigns/${reviewerCampaignId}`);

    expect(await screen.findByText(/\[2024\] SGCA 1/i)).toBeInTheDocument();
    expect(screen.getByText(/0\/2 fields submitted/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^open case$/i })).toBeInTheDocument();
    // Still-unclaimed work is grouped by case too, with a "claim the whole case" action and an
    // expandable per-field list underneath.
    expect(screen.getByText(/claimable review unit/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^claim entire case$/i })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^show fields$/i }));
    expect(screen.getByRole("button", { name: /^claim task$/i })).toBeInTheDocument();
    expect(screen.queryByText(/no items in this view/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/review queue could not be loaded/i)).not.toBeInTheDocument();
  });

  it("claims every open field of a case in one action via Claim entire case", async () => {
    const claimedIds: string[] = [];
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/me")) {
        return jsonResponse(reviewerMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.includes("/cases") && !url.includes("/campaigns?")) {
        return jsonResponse({ campaign_id: reviewerCampaignId, items: [] });
      }
      if (url.includes("/review/campaigns")) {
        return jsonResponse({
          campaigns: [
            {
              campaign_id: reviewerCampaignId,
              campaign_key: "claim-case",
              campaign_name: "Claim case campaign",
              not_started_count: 2,
              in_progress_count: 0,
              completed_count: 0,
              selected_group_ids: [],
            },
          ],
          schema_version: "reviewer-campaign-queue/v1",
        });
      }
      if (url.includes("/review/queue")) {
        return jsonResponse({
          items: [
            {
              review_unit_id: "00000000-0000-4000-8000-000000000901",
              campaign_id: reviewerCampaignId,
              case_id: "CASE-CLAIM-0001",
              subject_kind: "case",
              review_kind: "metadata_field",
              display_title: "Multi-field claimable case",
              display_subtitle: null,
              safe_field_label: "Neutral citation",
              assignment_id: null,
              assignment_status: "available",
            },
            {
              review_unit_id: "00000000-0000-4000-8000-000000000902",
              campaign_id: reviewerCampaignId,
              case_id: "CASE-CLAIM-0001",
              subject_kind: "case",
              review_kind: "metadata_field",
              display_title: "Multi-field claimable case",
              display_subtitle: null,
              safe_field_label: "Decision date",
              assignment_id: null,
              assignment_status: "available",
            },
          ],
          next_cursor: null,
        });
      }
      if (url.endsWith("/review/claim") && method === "POST") {
        const body = JSON.parse(String(init?.body)) as { review_unit_id: string };
        claimedIds.push(body.review_unit_id);
        return jsonResponse({
          assignment_id: `assignment-for-${body.review_unit_id}`,
          lock_version: 1,
        });
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/review/campaigns/${reviewerCampaignId}`);

    expect(await screen.findByText(/multi-field claimable case/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^claim entire case$/i }));

    await waitFor(() => expect(claimedIds).toHaveLength(2));
    expect(claimedIds).toEqual([
      "00000000-0000-4000-8000-000000000901",
      "00000000-0000-4000-8000-000000000902",
    ]);
  });

  it("stops and reports which field failed when claiming an entire case partially fails", async () => {
    let claimAttempts = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/me")) {
        return jsonResponse(reviewerMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.includes("/cases") && !url.includes("/campaigns?")) {
        return jsonResponse({ campaign_id: reviewerCampaignId, items: [] });
      }
      if (url.includes("/review/campaigns")) {
        return jsonResponse({
          campaigns: [
            {
              campaign_id: reviewerCampaignId,
              campaign_key: "claim-case-fail",
              campaign_name: "Claim case failure campaign",
              not_started_count: 2,
              in_progress_count: 0,
              completed_count: 0,
              selected_group_ids: [],
            },
          ],
          schema_version: "reviewer-campaign-queue/v1",
        });
      }
      if (url.includes("/review/queue")) {
        return jsonResponse({
          items: [
            {
              review_unit_id: "00000000-0000-4000-8000-000000000903",
              campaign_id: reviewerCampaignId,
              case_id: "CASE-CLAIM-0002",
              subject_kind: "case",
              review_kind: "metadata_field",
              display_title: "Partially claimable case",
              display_subtitle: null,
              safe_field_label: "Neutral citation",
              assignment_id: null,
              assignment_status: "available",
            },
            {
              review_unit_id: "00000000-0000-4000-8000-000000000904",
              campaign_id: reviewerCampaignId,
              case_id: "CASE-CLAIM-0002",
              subject_kind: "case",
              review_kind: "metadata_field",
              display_title: "Partially claimable case",
              display_subtitle: null,
              safe_field_label: "Coram",
              assignment_id: null,
              assignment_status: "available",
            },
          ],
          next_cursor: null,
        });
      }
      if (url.endsWith("/review/claim") && method === "POST") {
        claimAttempts += 1;
        if (claimAttempts === 1) {
          return jsonResponse({ assignment_id: "assignment-first", lock_version: 1 });
        }
        return jsonResponse({ code: "no_review_work_available" }, 409);
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${tenantId}/review/campaigns/${reviewerCampaignId}`);

    expect(await screen.findByText(/partially claimable case/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^claim entire case$/i }));

    expect(
      await screen.findByText(/"coram" was claimed by someone else first/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(claimAttempts).toBe(2));
  });

  it("shows backend unavailable only for true queue failures", async () => {
    mockReviewerQueueErrorApi(503, reviewerFailureTenantId);
    renderAt(`/t/${reviewerFailureTenantId}/review/campaigns/${reviewerCampaignId}`);

    expect(await screen.findByText(/review queue could not be loaded/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/you are not assigned reviewer access for this campaign/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/no items in this view/i)).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/review/queue")),
    ).toHaveLength(1);
  });

  it.each([
    { groupId: "cited_cases", empty: false },
    { groupId: "statutes_cited", empty: false },
    { groupId: "cited_cases", empty: true },
  ])(
    "checks $groupId additions and preserves the group after removal (empty: $empty)",
    async ({ groupId, empty }) => {
      const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
      const group = {
        ...syntheticBundle.field_groups[1],
        group_id: groupId,
        items: empty ? [] : syntheticBundle.field_groups[1].items,
        item_count: empty ? 0 : syntheticBundle.field_groups[1].item_count,
        add_item_label: groupId === "cited_cases" ? "cited case" : "statute reference",
      };
      let proposal: NonNullable<ReviewerGroupingBundle["reviewer_additions"]>[number] = {
        id: "00000000-0000-4000-8000-000000000abc",
        group_id: groupId,
        value_schema:
          groupId === "cited_cases" ? "cited_case_text/v1" : "statute_reference_text/v1",
        value: "New reference",
        original_value: "New reference",
        note: "",
        state: "draft",
        lock_version: 2,
        created_at: new Date().toISOString(),
        provenance: [
          {
            source_snapshot_id: syntheticBundle.source_render.source_snapshot_id,
            source_version: "a".repeat(64),
            char_start: 0,
            char_end: 5,
          },
        ],
      };
      let removed = false;
      let checks = 0;
      let submissions = 0;
      vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
        const url = String(input);
        if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
        if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
        if (url.endsWith("/grouped-bundle"))
          return jsonResponse({
            ...syntheticBundle,
            field_groups: [syntheticBundle.field_groups[0], group],
            reviewer_additions: removed ? [] : [proposal],
          });
        if (url.endsWith("/duplicate-check")) {
          checks += 1;
          return jsonResponse({
            fingerprint: "a",
            conflicts: [
              {
                item_id: syntheticBundle.field_groups[1].items[0].review_unit_id,
                value: "New reference",
                kind: "confirmed",
                reason: "Same value and provenance",
                submitted: false,
              },
            ],
          });
        }
        if (url.endsWith("/submitted")) {
          submissions += 1;
          return jsonResponse(
            {
              code: "citation_duplicate",
              title: "Duplicate item",
              detail: "Same value and provenance",
            },
            422,
          );
        }
        if (url.endsWith("/draft")) {
          proposal = {
            ...proposal,
            ...JSON.parse(String(init?.body)),
            lock_version: proposal.lock_version + 1,
          };
          return jsonResponse(proposal);
        }
        if (url.endsWith("/removed")) {
          removed = true;
          return jsonResponse({
            ...proposal,
            state: "removed",
            lock_version: proposal.lock_version + 1,
          });
        }
        if (url.endsWith("/source-render")) return jsonResponse({ detail: "not_found" }, 404);
        return jsonResponse({});
      });
      const user = userEvent.setup();
      renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
      await user.click(await screen.findByRole("button", { name: /Cited cases/ }));
      await user.click(await screen.findByRole("button", { name: /New reference/ }));
      const editor = screen.getByRole("region", { name: "Reviewer-added item editor" });
      expect(within(editor).queryByRole("heading")).toBeNull();
      await user.type(within(editor).getByLabelText("Proposed value"), " edited");
      await waitFor(() => expect(checks).toBeGreaterThan(0));
      expect(await within(editor).findByText(/Duplication detected,/)).toBeVisible();
      expect(screen.queryByText("No duplicate items found.")).toBeNull();
      expect(within(editor).getByRole("button", { name: "Submit field" })).toBeDisabled();
      fireEvent.keyDown(document.body, { key: "Enter" });
      expect(submissions).toBe(0);
      const previousChecks = checks;
      await user.click(within(editor).getByRole("button", { name: "Save draft" }));
      await waitFor(() => expect(checks).toBeGreaterThan(previousChecks));
      await user.click(within(editor).getByRole("button", { name: "Remove unsubmitted addition" }));
      await waitFor(() => expect(removed).toBe(true));
      await waitFor(() =>
        expect(screen.queryByRole("region", { name: "Reviewer-added item editor" })).toBeNull(),
      );
      expect(screen.queryByRole("button", { name: /New reference/ })).toBeNull();
      const nav = screen.getByRole("navigation", { name: "Grouped review fields" });
      if (empty) {
        expect(nav.querySelector("[data-review-item].is-active")).toBeNull();
        expect(within(nav).getByRole("button", { name: "+ Add cited case" })).toBeVisible();
        expect(screen.getByRole("switch", { name: "Show all citations" })).toBeEnabled();
      } else {
        expect(nav.querySelector("[data-review-item].is-active")).toHaveAttribute(
          "data-review-item",
          group.items.at(-1)!.review_unit_id,
        );
      }
    },
  );

  it("keeps highlight-to-add prefilled, checks it dynamically and opens the existing citation", async () => {
    mockReviewerStagingApi();
    const fallback = vi.mocked(globalThis.fetch).getMockImplementation()!;
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const existing = syntheticBundle.field_groups[1].items[0];
    const snippet = "Lee v Public Prosecutor [2015] SGCA 3";
    const start = syntheticBundle.source_render.content.indexOf(snippet);
    const end = start + snippet.length;
    const additions: NonNullable<ReviewerGroupingBundle["reviewer_additions"]> = [];
    let submitted = false;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/grouped-bundle"))
        return jsonResponse({
          ...syntheticBundle,
          proposal_source_version: "a".repeat(64),
          field_groups: syntheticBundle.field_groups.map((group) => ({
            ...group,
            add_item_label: group.group_id === "cited_cases" ? "cited case" : null,
          })),
          reviewer_additions: additions,
        });
      if (url.endsWith("/duplicate-check")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          value: snippet,
          provenance: [{ char_start: start, char_end: end }],
        });
        return jsonResponse({
          fingerprint: "a",
          conflicts: [
            {
              item_id: existing.review_unit_id,
              value: snippet,
              kind: "confirmed",
              reason: "Normalized substring",
              submitted: false,
            },
          ],
        });
      }
      if (url.includes("/proposals/") && url.endsWith("/draft")) {
        const body = JSON.parse(String(init?.body));
        const proposal = {
          ...body,
          id: url.split("/").at(-2)!,
          state: "draft" as const,
          original_value: body.value,
          value_schema: "cited_case_text/v1" as const,
          created_at: new Date().toISOString(),
          lock_version: 2,
        };
        additions.push(proposal);
        return jsonResponse(proposal);
      }
      if (url.endsWith("/submitted")) submitted = true;
      return fallback(input, init);
    });
    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await user.click(await screen.findByRole("button", { name: /Cited cases/ }));
    const source = document.querySelector(".source-text")!;
    const walker = document.createTreeWalker(source, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let offset = 0;
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const length = node.textContent!.length;
      if (start >= offset && start < offset + length) range.setStart(node, start - offset);
      if (end > offset && end <= offset + length) range.setEnd(node, end - offset);
      offset += length;
    }
    Object.defineProperty(range, "getBoundingClientRect", {
      value: () => new DOMRect(20, 100, 120, 20),
    });
    Object.defineProperty(range, "getClientRects", {
      value: () => [new DOMRect(20, 100, 120, 20)],
    });
    vi.spyOn(range, "cloneRange").mockReturnValue(range);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(source);
    await user.click(screen.getByRole("button", { name: /^Add cited case$/ }));
    const editor = await screen.findByRole("region", { name: "Reviewer-added item editor" });
    expect(within(editor).getByLabelText("Proposed value")).toHaveValue(snippet);
    expect(within(editor).getByText(`“${snippet}”`)).toBeVisible();
    expect(additions).toHaveLength(0);
    const link = await within(editor).findByRole("button", {
      name: `Click here to view the existing citation: ${snippet}`,
    });
    expect(within(editor).getByRole("button", { name: "Submit field" })).toBeDisabled();
    expect(submitted).toBe(false);
    await user.click(link);
    await waitFor(() =>
      expect(document.querySelector("[data-review-item].is-active")).toHaveAttribute(
        "data-review-item",
        existing.review_unit_id,
      ),
    );
    expect(additions).toHaveLength(1);
    expect(additions[0].value).toBe(snippet);
  });

  it("defaults provenance to No when value is marked No, but leaves it editable", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const [valueNo, provenanceNo] = screen.getAllByRole("button", { name: /^no$/i });
    await user.click(valueNo);
    expect(provenanceNo).toHaveAttribute("aria-pressed", "true");

    // Still editable: the reviewer can flip provenance back to Yes independently.
    const [, provenanceYes] = screen.getAllByRole("button", { name: /^yes$/i });
    await user.click(provenanceYes);
    expect(provenanceYes).toHaveAttribute("aria-pressed", "true");
    expect(provenanceNo).toHaveAttribute("aria-pressed", "false");
  });

  it("only offers to mark corrected provenance once provenance is answered No", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const markSpan = { name: /mark corrected provenance in source/i } as const;

    // Unanswered: there is nothing to correct, so the affordance is absent.
    expect(screen.queryByRole("button", markSpan)).not.toBeInTheDocument();

    const [, provenanceYes] = screen.getAllByRole("button", { name: /^yes$/i });
    await user.click(provenanceYes);
    expect(screen.queryByRole("button", markSpan)).not.toBeInTheDocument();

    const [, provenanceNo] = screen.getAllByRole("button", { name: /^no$/i });
    await user.click(provenanceNo);
    // The action lives in the right inspector, right next to the provenance question -- not just in
    // the source pane -- with a guidance sentence telling the reviewer what to do next.
    expect(await screen.findByRole("button", markSpan)).toBeInTheDocument();
    expect(
      screen.getByText(
        /select the text in the source that supports the corrected value\/evidence/i,
      ),
    ).toBeInTheDocument();

    // Flipping back to Yes withdraws the correction affordance again.
    await user.click(provenanceYes);
    expect(screen.queryByRole("button", markSpan)).not.toBeInTheDocument();
  });

  it("shows the selected provenance snippet text alongside the char range, and clear removes it", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const coramItem = syntheticBundle.field_groups[0].items[2];
    // Deliberately NOT the Coram field's own extracted value ("Justice A. Rahman") -- that string
    // already appears elsewhere on the page (the field list, the extracted-value panel), which would
    // make the marked-provenance assertions below ambiguous.
    const snippet = "the required intention";
    const charStart = syntheticBundle.source_render.content.indexOf(snippet);
    const charEnd = charStart + snippet.length;
    const bundleWithMarkedProvenance: ReviewerGroupingBundle = {
      ...syntheticBundle,
      field_groups: syntheticBundle.field_groups.map((group) => ({
        ...group,
        items: group.items.map((item) =>
          item.review_unit_id === coramItem.review_unit_id
            ? {
                ...item,
                status: "draft",
                answer_summary: {
                  state: "draft",
                  value_correct: true,
                  provenance_correct: false,
                  corrected_value_display: null,
                  comment: null,
                  failure_reason: null,
                  corrected_provenance_spans: [
                    {
                      evidence_window_id: item.evidence_window_ids[0],
                      char_start: charStart,
                      char_end: charEnd,
                      note: null,
                    },
                  ],
                },
              }
            : item,
        ),
      })),
    };

    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
      if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
      if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
        return jsonResponse(bundleWithMarkedProvenance);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /coram/i }));

    // Both the exact selected text and the char range are shown -- not offsets alone.
    expect(
      await screen.findByText(new RegExp(snippet), { selector: ".provenance-marked-text" }),
    ).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`chars ${charStart}.${charEnd}`))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^clear$/i }));
    expect(
      screen.queryByText(new RegExp(snippet), { selector: ".provenance-marked-text" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/chars \d+.\d+/)).not.toBeInTheDocument();
  });

  it("never shows reviewers the atomic/non-atomic field-group jargon", async () => {
    mockReviewerStagingApi();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    expect(screen.queryByText(/non[- ]?atomic/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^atomic$/i)).not.toBeInTheDocument();
    // The repeatable (non-atomic) group carries neutral reviewer language, never "repeatable".
    expect(screen.queryByText(/repeatable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/multiple entries/i)).not.toBeInTheDocument();
  });

  it("blocks submit on an incorrect value with no correction, and unblocks once one is added", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const [valueNo] = screen.getAllByRole("button", { name: /^no$/i });
    await user.click(valueNo);

    expect(
      await screen.findByText(/add a corrected value or a comment before submitting/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^submit field$/i })).toBeDisabled();

    await user.type(screen.getByLabelText(/corrected value/i), "[2017] SGHC 12A");
    expect(
      screen.queryByText(/add a corrected value or a comment before submitting/i),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^submit field$/i })).toBeEnabled();
  });

  it("persists the selected reason for an incorrect answer", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const [valueNo] = screen.getAllByRole("button", { name: /^no$/i });
    await user.click(valueNo);
    await user.selectOptions(screen.getByRole("combobox"), "evidence_wrong_location");

    expect(screen.getByRole("combobox")).toHaveValue("evidence_wrong_location");
  });

  it("updates the inspector and active highlight when a cited-case member is selected", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    // Cited cases is a repeatable group and collapses by default; open it, then pick the 2nd member.
    await user.click(screen.getByRole("button", { name: /cited cases/i }));
    const ngButtons = await screen.findAllByRole("button", { name: /ng v comptroller/i });
    await user.click(ngButtons[0]);

    expect(await screen.findByRole("heading", { name: /^ng v comptroller$/i })).toBeInTheDocument();
    // The left nav is the single member list (the former standalone member-index column is gone);
    // the picked member is visibly marked as selected there.
    const selected = screen.getByRole("button", { name: /ng v comptroller .*\(/i });
    expect(selected).toHaveClass("is-active");
    expect(document.querySelector(".compact-item-index")).toBeNull();
  });

  it("collapses a repeatable field group and reveals its members on demand", async () => {
    mockReviewerStagingApi();
    const user = userEvent.setup();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    // Atomic case-metadata fields are listed inline; the repeatable Cited cases group (2 members) is
    // collapsed by default, so its members are not flooding the field list.
    expect(screen.getByRole("button", { name: /neutral citation/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /lee v public prosecutor/i }),
    ).not.toBeInTheDocument();

    // Opening the group reveals its members.
    await user.click(screen.getByRole("button", { name: /cited cases/i }));
    expect(
      (await screen.findAllByRole("button", { name: /lee v public prosecutor/i })).length,
    ).toBeGreaterThan(0);
  });

  it("hydrates a previously submitted field's green dot and corrections from the server on load", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[1].assignment_id;
    const reviewUnitId = syntheticBundle.field_groups[0].items[1].review_unit_id;
    const submittedBundle: ReviewerGroupingBundle = {
      ...syntheticBundle,
      field_groups: syntheticBundle.field_groups.map((group) => ({
        ...group,
        items: group.items.map((item) =>
          item.review_unit_id === reviewUnitId
            ? {
                ...item,
                status: "submitted",
                answer_summary: {
                  state: "submitted",
                  value_correct: false,
                  provenance_correct: false,
                  corrected_value_display: "17 February 2017",
                  comment: "Date was misread from the header.",
                  failure_reason: "value_incorrect",
                  corrected_provenance_spans: [],
                },
              }
            : item,
        ),
      })),
    };

    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) {
        return jsonResponse(reviewerWorkspaceMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
        return jsonResponse(submittedBundle);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    // The green dot/"submitted" status is server-derived and visible without any interaction; the
    // nav card's title attribute carries it since the compact nav no longer shows a visible legend.
    const submittedCard = await screen.findByTitle(/— submitted$/i);
    expect(submittedCard).toBeInTheDocument();
    expect(submittedCard.querySelector(".status-dot-submitted")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: /decision date/i }));
    expect(await screen.findByDisplayValue("17 February 2017")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/date was misread from the header/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("value_incorrect");
  });

  it("submits every field then explicitly submits the case from the case-submit preview", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const oneItemBundle: ReviewerGroupingBundle = {
      ...syntheticBundle,
      field_groups: [
        { ...syntheticBundle.field_groups[0], items: [syntheticBundle.field_groups[0].items[0]] },
      ],
      progress: {
        total_items: 1,
        completed_items: 0,
        remaining_items: 1,
        group_progress: [{ group_id: "case_metadata", completed_count: 0, item_count: 1 }],
      },
    };
    const caseSubmitCalls: string[] = [];

    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/me")) {
        return jsonResponse(reviewerWorkspaceMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
        return jsonResponse(oneItemBundle);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/answer/submit`) && method === "POST") {
        return jsonResponse({ status: "submitted", lock_version: 2 });
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/case-submit`) && method === "POST") {
        caseSubmitCalls.push(url);
        return jsonResponse({
          case_id: "CASE-STAGING-0001",
          campaign_id: reviewerCampaignId,
          submitted_at: "2026-07-10T00:00:00Z",
          replayed: false,
        });
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const [valueYes, provenanceYes] = screen.getAllByRole("button", { name: /^yes$/i });
    await user.click(valueYes);
    await user.click(provenanceYes);

    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    expect(
      await screen.findByRole("img", { name: /fields submitted: 0% complete/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/once you submit this case, it is final and cannot be edited again/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save all as draft$/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /confirm & submit case/i }));

    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
  });

  it("opens the case-submit preview after the final outstanding field is submitted", async () => {
    const firstItem = syntheticBundle.field_groups[0].items[0];
    const secondItem = syntheticBundle.field_groups[0].items[1];
    const bundle: ReviewerGroupingBundle = {
      ...syntheticBundle,
      field_groups: [
        {
          ...syntheticBundle.field_groups[0],
          items: [
            firstItem,
            {
              ...secondItem,
              status: "submitted",
              answer_summary: {
                state: "submitted",
                value_correct: true,
                provenance_correct: true,
                corrected_value_display: null,
                comment: null,
                failure_reason: null,
                corrected_provenance_spans: [],
              },
            },
          ],
        },
      ],
      progress: {
        total_items: 2,
        completed_items: 1,
        remaining_items: 1,
        group_progress: [{ group_id: "case_metadata", completed_count: 1, item_count: 2 }],
      },
    };

    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
      if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
      if (url.endsWith(`/review/assignments/${firstItem.assignment_id}/grouped-bundle`)) {
        return jsonResponse(bundle);
      }
      if (url.endsWith(`/review/assignments/${firstItem.assignment_id}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      if (
        url.endsWith(`/review/assignments/${firstItem.assignment_id}/answer/submit`) &&
        method === "POST"
      ) {
        return jsonResponse({ status: "submitted", lock_version: 2 }, 201);
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${firstItem.assignment_id}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);

    // The remaining field is first, not last, in display order. Its successful submission should
    // open the same preview as the header action and reflect the newly completed 2/2 state.
    await user.click(screen.getByRole("button", { name: /^submit field$/i }));

    const previewHeading = await screen.findByRole("heading", {
      name: /review before you submit this case/i,
    });
    expect(previewHeading).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /fields submitted: 100% complete/i }),
    ).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getAllByText(/^submitted$/i)).toHaveLength(2);
  });

  it("keeps the reviewer in the fields when a submitted field is not the final outstanding one", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    mockWorkspaceWrites(assignmentId, (kind) => {
      if (kind !== "submit") return jsonResponse({ status: "draft", lock_version: 2 });
      return jsonResponse({ status: "submitted", lock_version: 2 }, 201);
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);
    await user.click(screen.getByRole("button", { name: /^submit field$/i }));

    expect(await screen.findByTitle(/— submitted$/i)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("case submit auto-retries a per-field stale conflict instead of aborting with a banner", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const oneItem = syntheticBundle.field_groups[0].items[0];
    const bundleAt = (lockVersion: number): ReviewerGroupingBundle => ({
      ...syntheticBundle,
      field_groups: [
        { ...syntheticBundle.field_groups[0], items: [{ ...oneItem, lock_version: lockVersion }] },
      ],
      lock_version: lockVersion,
      progress: {
        total_items: 1,
        completed_items: 0,
        remaining_items: 1,
        group_progress: [{ group_id: "case_metadata", completed_count: 0, item_count: 1 }],
      },
    });
    let bundleFetches = 0;
    const submitIfMatches: (string | null)[] = [];
    const caseSubmitCalls: string[] = [];

    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
      if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
      if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
        bundleFetches += 1;
        // First load carries version 1; the auto-retry's refetch returns the moved-on version 2.
        return jsonResponse(bundleAt(bundleFetches === 1 ? 1 : 2));
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/answer/submit`) && method === "POST") {
        const ifMatch = new Headers(init?.headers).get("If-Match");
        submitIfMatches.push(ifMatch);
        // A submit that still carries the stale version 1 conflicts; version 2 (from the refetch)
        // succeeds.
        if (ifMatch !== '"2"') {
          return jsonResponse({ code: "precondition_failed", detail: "stale" }, 412);
        }
        return jsonResponse({ status: "submitted", lock_version: 3 }, 201);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/case-submit`) && method === "POST") {
        caseSubmitCalls.push(url);
        return jsonResponse({
          case_id: "CASE-STAGING-0001",
          campaign_id: reviewerCampaignId,
          submitted_at: "2026-07-10T00:00:00Z",
          replayed: false,
        });
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    const [valueYes, provenanceYes] = screen.getAllByRole("button", { name: /^yes$/i });
    await user.click(valueYes);
    await user.click(provenanceYes);

    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    await user.click(await screen.findByRole("button", { name: /confirm & submit case/i }));

    // The stale first attempt is transparently retried with the refreshed version; the case then
    // submits and the preview closes -- no per-field failure banner.
    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
    expect(submitIfMatches).toEqual(['"1"', '"2"']);
    expect(screen.queryByText(/could not be submitted/i)).not.toBeInTheDocument();
  });

  it("enables case submit (no '0 field(s)') and hides Save-all-as-draft when every field is already submitted", async () => {
    const caseSubmitCalls: string[] = [];
    const assignmentId = mockAllFieldsSubmitted(caseSubmitCalls);
    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));

    const confirm = await screen.findByRole("button", { name: /^confirm & submit case$/i });
    expect(confirm).toBeEnabled();
    // The old bug rendered "Confirm & submit case (0 field(s))" and left the button disabled.
    expect(screen.queryByText(/\(0 field\(s\)\)/i)).not.toBeInTheDocument();
    // Nothing is unsaved, so the redundant "Save all as draft" action is absent.
    expect(screen.queryByRole("button", { name: /save all as draft/i })).not.toBeInTheDocument();

    await user.click(confirm);
    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
  });

  it("closes the case-submit preview via the X button without submitting the case", async () => {
    const caseSubmitCalls: string[] = [];
    const assignmentId = mockAllFieldsSubmitted(caseSubmitCalls);
    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^close$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(caseSubmitCalls).toHaveLength(0);
  });

  it("navigates to the next assigned case immediately after a successful final case submit", async () => {
    const caseSubmitCalls: string[] = [];
    const nextAssignmentId = "00000000-0000-4000-8000-000000000902";
    const nextBundle: ReviewerGroupingBundle = {
      ...syntheticBundle,
      case_header: { ...syntheticBundle.case_header, case_title: "Re Next Assigned Case" },
      field_groups: syntheticBundle.field_groups.map((group) => ({
        ...group,
        items: group.items.map((item) => ({ ...item, assignment_id: nextAssignmentId })),
      })),
    };
    const assignmentId = mockReadyCaseWithNav({
      caseSubmitCalls,
      nextCase: {
        assignmentId: nextAssignmentId,
        caseTitle: "Re Next Assigned Case",
        bundle: nextBundle,
      },
    });
    const user = userEvent.setup();
    renderAt(
      `/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}?campaignId=${reviewerCampaignId}`,
    );

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    await user.click(await screen.findByRole("button", { name: /^confirm & submit case$/i }));

    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
    // Landed on the next case's workspace without a manual Next click, with a brief success toast.
    expect(
      await screen.findByRole("heading", { name: /re next assigned case/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/case submitted\. opening next case/i)).toBeInTheDocument();
  });

  it("returns to the campaign queue after a successful final case submit when it was the last case", async () => {
    const caseSubmitCalls: string[] = [];
    const assignmentId = mockReadyCaseWithNav({ caseSubmitCalls });
    const user = userEvent.setup();
    renderAt(
      `/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}?campaignId=${reviewerCampaignId}`,
    );

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    await user.click(await screen.findByRole("button", { name: /^confirm & submit case$/i }));

    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
    // Landed back on the campaign case list, with a brief success toast.
    expect(
      await screen.findByRole("heading", { name: /reviewer staging campaign/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/case submitted\. returning to campaign queue/i),
    ).toBeInTheDocument();
  });

  it("does not navigate away when the final case submit fails", async () => {
    const caseSubmitCalls: string[] = [];
    const assignmentId = mockReadyCaseWithNav({ caseSubmitCalls, caseSubmitStatus: 500 });
    const user = userEvent.setup();
    renderAt(
      `/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}?campaignId=${reviewerCampaignId}`,
    );

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));
    await user.click(await screen.findByRole("button", { name: /^confirm & submit case$/i }));

    await waitFor(() => expect(caseSubmitCalls).toHaveLength(1));
    // Still on the same case, preview still open, friendly error shown -- no navigation happened.
    expect(
      screen.getByRole("heading", { name: /public prosecutor v tan wei ming/i }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/could not be submitted/i)).toBeInTheDocument();
    expect(screen.queryByText(/case submitted/i)).not.toBeInTheDocument();
  });

  it("sends only one submit when Submit field is triggered twice while a request is in flight", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const submitCalls: string[] = [];
    const deferred: { release: () => void } = { release: () => {} };
    mockWorkspaceWrites(assignmentId, (kind, init) => {
      if (kind !== "submit") return jsonResponse({ status: "draft", lock_version: 2 });
      submitCalls.push(String(init?.method));
      return new Promise<Response>((resolve) => {
        deferred.release = () =>
          resolve(
            new Response(JSON.stringify({ status: "submitted", lock_version: 2 }), {
              status: 201,
              headers: { "content-type": "application/json" },
            }),
          );
      });
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);

    const submit = screen.getByRole("button", { name: /^submit field$/i });
    await user.click(submit);
    // The request is deferred, so the button is disabled and a re-trigger (a second click, or the
    // Enter shortcut) must not fire a second submit while the first is in flight.
    expect(submit).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(submitCalls).toHaveLength(1);

    deferred.release();
    // The nav card's title attribute carries the real per-item status once the compact nav no
    // longer shows a visible "Submitted" legend; the active pane may already have advanced to the
    // next field by this point.
    expect(await screen.findByTitle(/— submitted$/i)).toBeInTheDocument();
    expect(submitCalls).toHaveLength(1);
  });

  it("treats a 409 already-submitted response as a completed field, not a stale conflict", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    mockWorkspaceWrites(assignmentId, (kind) => {
      if (kind !== "submit") return jsonResponse({ status: "draft", lock_version: 2 });
      return jsonResponse(
        { code: "assignment_not_editable", detail: "The assignment can no longer be changed." },
        409,
      );
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);
    await user.click(screen.getByRole("button", { name: /^submit field$/i }));

    // The field lands as submitted (green), and no raw conflict wording is shown to the reviewer.
    // The nav card's title attribute carries the real per-item status once the compact nav no
    // longer shows a visible "Submitted" legend; the active pane may already have advanced to the
    // next field by this point.
    expect(await screen.findByTitle(/— submitted$/i)).toBeInTheDocument();
    expect(screen.queryByText(/updated after you loaded it/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/changed since you loaded it/i)).not.toBeInTheDocument();
  });

  it("submits with the version returned by an immediately-preceding draft save", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    let submitIfMatch: string | null = null;
    // The draft save bumps the server-side version to 5; the following submit must send If-Match
    // "5". A submit that still carried the bundle's original version 1 would 412 here.
    mockWorkspaceWrites(assignmentId, (kind, init) => {
      if (kind === "draft") return jsonResponse({ status: "draft", lock_version: 5 });
      submitIfMatch = new Headers(init?.headers).get("If-Match");
      if (submitIfMatch !== '"5"') {
        return jsonResponse({ code: "precondition_failed", detail: "stale" }, 412);
      }
      return jsonResponse({ status: "submitted", lock_version: 6 }, 201);
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);
    await user.click(screen.getByRole("button", { name: /^save draft$/i }));
    expect((await screen.findAllByText(/^draft saved$/i)).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /^submit field$/i }));

    // The nav card's title attribute carries the real per-item status once the compact nav no
    // longer shows a visible "Submitted" legend; the active pane may already have advanced to the
    // next field by this point.
    expect(await screen.findByTitle(/— submitted$/i)).toBeInTheDocument();
    expect(submitIfMatch).toBe('"5"');
    expect(screen.queryByText(/updated after you loaded it/i)).not.toBeInTheDocument();
  });

  it("shows a friendly, refreshable message on a true stale-version conflict", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    mockWorkspaceWrites(assignmentId, (kind) => {
      if (kind !== "submit") return jsonResponse({ status: "draft", lock_version: 2 });
      return jsonResponse({ code: "precondition_failed", detail: "stale" }, 412);
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await answerCurrentFieldYes(user);
    await user.click(screen.getByRole("button", { name: /^submit field$/i }));

    expect(
      await screen.findByText(/this field was updated after you loaded it/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh and retry/i })).toBeInTheDocument();
  });

  it("locates the current case for Prev/Next even when entered via a non-anchor field assignment", async () => {
    // The reviewer opened this case via a freshly claimed field, so the route assignmentId is NOT
    // the case's anchor_assignment_id. Nav must still find the case by its identity (title +
    // citations from the bundle header) and enable Next when a later case exists.
    const routeAssignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const otherAnchor = "00000000-0000-4000-8000-000000000902";
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(reviewerWorkspaceMe);
      if (url.endsWith("/auth/csrf")) return jsonResponse({ csrf_token: "csrf-token" });
      if (url.includes("/cases")) {
        return jsonResponse({
          campaign_id: reviewerCampaignId,
          items: [
            {
              case_id: "CASE-STAGING-0001",
              case_title: syntheticBundle.case_header.case_title,
              neutral_citation_display: syntheticBundle.case_header.neutral_citation_display,
              reported_citation_display: null,
              campaign_id: reviewerCampaignId,
              // Deliberately different from the route assignment: this reviewer entered via a
              // non-anchor field.
              anchor_assignment_id: "00000000-0000-4000-8000-000000000901",
              fields_assigned: 3,
              fields_submitted: 0,
              status: "in_progress",
            },
            {
              case_id: "CASE-STAGING-0002",
              case_title: "Some Other Case",
              neutral_citation_display: "[2018] SGHC 99",
              reported_citation_display: null,
              campaign_id: reviewerCampaignId,
              anchor_assignment_id: otherAnchor,
              fields_assigned: 2,
              fields_submitted: 0,
              status: "in_progress",
            },
          ],
          has_more: false,
          next_cursor: null,
          schema_version: "reviewer-case-queue/v1",
        });
      }
      if (url.includes("/review/campaigns")) {
        return jsonResponse({
          campaigns: [
            {
              campaign_id: reviewerCampaignId,
              campaign_key: "reviewer-staging",
              campaign_name: "Reviewer staging campaign",
              not_started_count: 0,
              in_progress_count: 2,
              completed_count: 0,
              selected_group_ids: [],
            },
          ],
          schema_version: "reviewer-campaign-queue/v1",
        });
      }
      if (url.endsWith(`/review/assignments/${routeAssignmentId}/grouped-bundle`)) {
        return jsonResponse(syntheticBundle);
      }
      if (url.endsWith(`/review/assignments/${routeAssignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      return jsonResponse({});
    });

    renderAt(
      `/t/${reviewerWorkspaceTenantId}/review/task/${routeAssignmentId}?campaignId=${reviewerCampaignId}`,
    );
    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });

    // First case in the ordered list: Previous disabled, Next enabled (a later case exists) --
    // despite the route assignment not being this case's anchor.
    const nextButton = await screen.findByRole("button", { name: /next case/i });
    await waitFor(() => expect(nextButton).toBeEnabled());
    expect(screen.getByRole("button", { name: /previous case/i })).toBeDisabled();
  });

  it("gives the case workspace a focused shell: no primary-nav sidebar, a compact back breadcrumb, and a fixed footer with case navigation", async () => {
    mockReviewerStagingApi();
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    // The global primary-nav sidebar (Reviewer queue / Admin / …) is hidden on reviewer routes so
    // the source pane can dominate.
    expect(
      screen.queryByRole("navigation", { name: /primary navigation/i }),
    ).not.toBeInTheDocument();
    // Back navigation is a compact breadcrumb, not the old full-width footer link.
    expect(screen.getByRole("link", { name: /back to campaign queue/i })).toHaveClass(
      "breadcrumb-back",
    );
    // Fixed footer: within-campaign case navigation above the brand line.
    expect(screen.getByRole("navigation", { name: /case navigation/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to campaign queue/i })).toBeInTheDocument();
    expect(document.querySelector(".app-footer-brand")).toBeInTheDocument();
  });

  it("shows a compact back-to-campaigns breadcrumb on the campaign case list, not a full-width button or a duplicate queue pill", async () => {
    mockReviewerStagingApi();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/campaigns/${reviewerCampaignId}`);

    const back = await screen.findByRole("link", { name: /back to your campaigns/i });
    expect(back).toHaveClass("breadcrumb-back");
    expect(screen.queryByText(/^review queue$/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sign out or switch account/i }),
    ).not.toBeInTheDocument();
    // Reviewer pages carry the brand footer.
    expect(document.querySelector(".app-footer-brand")).toBeInTheDocument();
  });

  it("shows case title, campaign name, comment/reason, and highlights incomplete fields in the case-submit preview", async () => {
    const assignmentId = syntheticBundle.field_groups[0].items[0].assignment_id;
    const answeredUnitId = syntheticBundle.field_groups[0].items[1].review_unit_id;
    const previewBundle: ReviewerGroupingBundle = {
      ...syntheticBundle,
      field_groups: syntheticBundle.field_groups.map((group) => ({
        ...group,
        items: group.items.map((item) =>
          item.review_unit_id === answeredUnitId
            ? {
                ...item,
                status: "submitted",
                answer_summary: {
                  state: "submitted",
                  value_correct: false,
                  provenance_correct: false,
                  corrected_value_display: "17 February 2017",
                  comment: "Date was misread from the header.",
                  failure_reason: "value_incorrect",
                  corrected_provenance_spans: [],
                },
              }
            : item,
        ),
      })),
    };

    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) {
        return jsonResponse(reviewerWorkspaceMe);
      }
      if (url.endsWith("/auth/csrf")) {
        return jsonResponse({ csrf_token: "csrf-token" });
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/grouped-bundle`)) {
        return jsonResponse(previewBundle);
      }
      if (url.endsWith(`/review/assignments/${assignmentId}/source-render`)) {
        return jsonResponse({ detail: "not_found" }, 404);
      }
      return jsonResponse({});
    });

    const user = userEvent.setup();
    renderAt(`/t/${reviewerWorkspaceTenantId}/review/task/${assignmentId}`);

    await screen.findByRole("heading", { name: /public prosecutor v tan wei ming/i });
    await user.click(screen.getByRole("button", { name: /review & submit case/i }));

    const dialog = await screen.findByRole("dialog");
    const withinDialog = within(dialog);
    expect(
      withinDialog.getByText(/public prosecutor v tan wei ming/i, { selector: "strong" }),
    ).toBeInTheDocument();
    expect(
      withinDialog.getByText(/demo workspace synthetic reviewer campaign/i),
    ).toBeInTheDocument();
    expect(withinDialog.getByText(/date was misread from the header/i)).toBeInTheDocument();
    expect(withinDialog.getByText(/^value is incorrect$/i)).toBeInTheDocument();
    // "Neutral citation" (a different field in the same case) was never answered, so its preview
    // row must surface as incomplete rather than silently look the same as an answered one.
    const incompleteRow = withinDialog.getByRole("row", { name: /neutral citation/i });
    expect(incompleteRow).toHaveTextContent(/incomplete -- required answer missing/i);
    expect(incompleteRow.className).toContain("preview-row-incomplete");
  });
});
