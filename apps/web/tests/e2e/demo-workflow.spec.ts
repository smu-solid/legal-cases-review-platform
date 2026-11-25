import { expect, test, type APIResponse, type Page } from "@playwright/test";

const password = "Browser-demo-password-2026";
type Item = {
  review_unit_id: string;
  assignment_id: string;
  item_label: string;
  evidence_windows: { snippet: string }[];
};
type ReviewBundle = { field_groups: { items: Item[] }[]; case_submitted: boolean };
type AdjudicationItem = {
  adjudication_id: string;
  submissions: { submission_id: string }[];
};
type AdjudicationBundle = { field_groups: { items: AdjudicationItem[] }[] };

async function json<T>(response: APIResponse): Promise<T> {
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json() as Promise<T>;
}

async function login(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto("/sign-in");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel(/^Account menu for /)).toBeVisible();
  return json<{ id: string; memberships: { tenant_id: string }[] }>(
    await page.request.get("/api/v1/auth/me"),
  );
}

async function write<T>(page: Page, path: string, body?: unknown) {
  const { csrf_token } = await json<{ csrf_token: string }>(
    await page.request.get("/api/v1/auth/csrf"),
  );
  return json<T>(
    await page.request.post(`/api/v1${path}`, {
      data: body,
      headers: {
        Origin: "http://localhost:5273",
        "X-CSRF-Token": csrf_token,
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
  );
}

for (const width of [1440, 900]) {
  test(`SQLite demo review and adjudication at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const admin = await login(page, "admin@example.test");
    const tenant = admin.memberships[0].tenant_id;
    const roster = await json<{ items: { user_id: string; display_name: string }[] }>(
      await page.request.get(`/api/v1/admin/tenants/${tenant}/reviewers`),
    );
    const reviewers = roster.items.filter((item) => /Reviewer (One|Two)/.test(item.display_name));
    expect(reviewers).toHaveLength(2);
    const campaign = await write<{ campaign_id: string }>(
      page,
      `/admin/tenants/${tenant}/review/campaigns`,
      {
        campaign_key: `browser-${width}`,
        campaign_name: `Browser demonstration ${width}`,
        requested_case_count: 1,
        review_scope: { group_ids: ["case_metadata", "cited_cases"] },
        reviews_per_case: 2,
      },
    );
    const runs = `/admin/tenants/${tenant}/campaigns/${campaign.campaign_id}/allocation-runs`;
    const run = await write<{ run_id: string }>(page, runs, {
      subject_kind: "case",
      review_kind: "metadata_field",
      target_distinct_subjects: 1,
      target_per_reviewer_workload: 1,
      target_pairwise_overlap: 1,
      target_global_overlap: 1,
      rolling_window_size: 0,
      rolling_window_stride: 0,
      hub_priority_count: 1,
      random_seed: "browser-demo",
      allocation_policy_version: "reviewer-allocation/v1",
      reviewer_ids: reviewers.map((reviewer) => reviewer.user_id),
      metric_weights: {},
    });
    await write(page, `${runs}/${run.run_id}/publish`);

    for (const email of ["reviewer1@example.test", "reviewer2@example.test"]) {
      await login(page, email);
      const queue = await json<{ items: { assignment_id: string }[] }>(
        await page.request.get(
          `/api/v1/tenants/${tenant}/review/queue?campaign_id=${campaign.campaign_id}`,
        ),
      );
      const claimed = queue.items[0];
      expect(claimed.assignment_id).toBeTruthy();
      const base = `/tenants/${tenant}/review/assignments/${claimed.assignment_id}`;
      const bundle = await json<ReviewBundle>(
        await page.request.get(`/api/v1${base}/grouped-bundle`),
      );
      const items = bundle.field_groups.flatMap((group) => group.items);
      expect(items.length).toBeGreaterThan(0);
      await page.goto(`/t/${tenant}/review/task/${claimed.assignment_id}`);
      await expect(page.locator(".source-text")).toContainText("fictional judgment");
      await expect(page.locator(".source-text mark").first()).toBeVisible();
      const titleBox = await page.locator(".workspace-header-center").boundingBox();
      expect(titleBox).not.toBeNull();
      for (const action of await page.locator(".workspace-header-right > *").all()) {
        const box = await action.boundingBox();
        expect(box).not.toBeNull();
        const separated =
          box!.x + box!.width <= titleBox!.x ||
          titleBox!.x + titleBox!.width <= box!.x ||
          box!.y + box!.height <= titleBox!.y ||
          titleBox!.y + titleBox!.height <= box!.y;
        expect(separated, "Workspace title and actions must not overlap").toBe(true);
      }
      await page.screenshot({
        path: test.info().outputPath("review-workspace.png"),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Document", exact: true }).click();
      const document = page.frameLocator(".source-frame");
      await expect(document.locator("body")).toContainText("fictional");
      await expect(page.locator(".source-frame")).toHaveAttribute("sandbox", "");
      await expect(document.locator("mark, script, .rp-citation-action")).toHaveCount(0);
      const citedCase = items.find((item) => item.item_label === "Cited case")!;
      expect(citedCase).toBeDefined();
      await page.locator(`[data-review-item="${citedCase.review_unit_id}"]`).click();
      await expect(document.locator("mark, script, .rp-citation-action")).toHaveCount(0);
      await page.getByRole("button", { name: "Text", exact: true }).click();
      for (const [index, item] of items.entries()) {
        await page.locator(`[data-review-item="${item.review_unit_id}"]`).click();
        await expect(page.locator('.source-text mark[data-active-anchor="true"]')).toHaveText(
          item.evidence_windows[0].snippet,
        );
        const panel = page.locator(".answer-pane");
        await panel
          .getByRole("group", { name: /^Is the extracted value correct/ })
          .getByRole("button", { name: "Yes", exact: true })
          .click();
        await panel
          .getByRole("group", { name: /^Is the highlighted provenance correct/ })
          .getByRole("button", { name: "Yes", exact: true })
          .click();
        if (index === 0) {
          await panel.getByRole("button", { name: "Save draft", exact: true }).click();
          await expect(panel.getByText("Draft saved", { exact: true })).toBeVisible();
          await page.reload();
          await expect(
            page.locator(".answer-pane").getByRole("button", { name: "Yes", exact: true }).first(),
          ).toHaveAttribute("aria-pressed", "true");
        }
        const submitted = page.waitForResponse((response) =>
          response.url().endsWith("/answer/submit"),
        );
        await panel.getByRole("button", { name: "Submit field", exact: true }).click();
        expect((await submitted).status()).toBe(201);
      }
      await write(page, `${base}/case-submit`);
      const final = await json<ReviewBundle>(
        await page.request.get(`/api/v1${base}/grouped-bundle`),
      );
      expect(final.case_submitted).toBe(true);
    }

    for (const email of ["adjudicator@example.test", "admin@example.test"]) {
      await login(page, email);
      const queue = await json<{
        items: { workspace_adjudication_id: string; campaign_id: string }[];
      }>(
        await page.request.get(
          `/api/v1/tenants/${tenant}/review/adjudication-campaigns/${campaign.campaign_id}/cases`,
        ),
      );
      const item = queue.items[0];
      expect(item).toBeDefined();
      const anchor = item!.workspace_adjudication_id;
      const bundle = await json<AdjudicationBundle>(
        await page.request.get(
          `/api/v1/tenants/${tenant}/review/adjudications/${anchor}/grouped-bundle`,
        ),
      );
      await page.goto(`/t/${tenant}/adjudication/${anchor}`);
      await expect(
        page.getByRole("radio", { name: "All equivalent / supported", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Document", exact: true }).click();
      await expect(page.frameLocator(".source-frame").locator("body")).toContainText("fictional");
      await expect(page.locator(".source-frame")).toHaveAttribute("sandbox", "");
      await expect(page.frameLocator(".source-frame").locator("mark, script")).toHaveCount(0);
      await page.getByRole("button", { name: "Text", exact: true }).click();
      await expect(page.locator(".source-text mark").first()).toBeVisible();
      for (const field of bundle.field_groups.flatMap((group) => group.items)) {
        await write(
          page,
          `/tenants/${tenant}/review/adjudications/${field.adjudication_id}/submit`,
          {
            outcome: "all_equivalent_supported",
            reviewer_assessments: field.submissions.map((submission) => ({
              submission_id: submission.submission_id,
              assessment: "correct",
            })),
          },
        );
      }
    }
    const progress = await json<{
      items: {
        campaign_id: string;
        total_units: number;
        unit_status_counts: { resolved: number };
      }[];
    }>(await page.request.get(`/api/v1/admin/tenants/${tenant}/review/campaign-progress`));
    const completed = progress.items.find((entry) => entry.campaign_id === campaign.campaign_id)!;
    expect(completed.unit_status_counts.resolved).toBe(completed.total_units);
    expect(completed.total_units).toBeGreaterThan(0);
    await page.getByLabel(/^Account menu for /).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
    expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  });
}
