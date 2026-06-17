import { test, expect } from "@playwright/test";

const TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZXYtYW5hbHlzdCIsInJvbGVzIjpbImFuYWx5c3QiXSwiZXhwIjo5OTk5OTk5OTk5fQ.fake";

const TASKS = {
  api_version: "1",
  total: 2,
  items: [
    {
      task_id: "task-001",
      question_text: "What is the revenue trend for Q3?",
      confidence_score: 0.45,
      source: "query",
      status: "open",
      submitted_by: "dev-analyst",
      created_at: "2026-06-01T10:00:00Z",
    },
    {
      task_id: "task-002",
      question_text: "Missing cost center mapping for EMEA",
      confidence_score: null,
      source: "manual",
      status: "resolved",
      submitted_by: null,
      created_at: "2026-05-28T08:30:00Z",
    },
  ],
};

test.describe("Enrichment task list", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.evaluate((t) => localStorage.setItem("kdaf_token", t), TOKEN);

    await page.route("/api/v1/enrichment/tasks**", (route) => {
      const url = new URL(route.request().url());
      const status = url.searchParams.get("status") ?? "open";
      const filtered = status === "all"
        ? TASKS.items
        : TASKS.items.filter((t) => t.status === status);
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...TASKS, items: filtered, total: filtered.length }),
      });
    });
  });

  test("redirects to /login when not authenticated", async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem("kdaf_token"));
    await page.goto("/enrichment");
    await page.waitForURL("**/login");
  });

  test("renders the page heading and task count", async ({ page }) => {
    await page.goto("/enrichment");
    await expect(page.getByRole("heading", { name: /enrichment tasks/i })).toBeVisible();
    await expect(page.getByText(/\d+ tasks? total/i)).toBeVisible();
  });

  test("shows open tasks by default", async ({ page }) => {
    await page.goto("/enrichment");
    await expect(page.getByText("What is the revenue trend for Q3?")).toBeVisible();
    await expect(page.getByText("Missing cost center mapping for EMEA")).not.toBeVisible();
  });

  test("filter buttons — open, resolved, all", async ({ page }) => {
    await page.goto("/enrichment");
    // Switch to resolved
    await page.getByRole("button", { name: "resolved" }).click();
    await expect(page.getByText("Missing cost center mapping for EMEA")).toBeVisible();
    await expect(page.getByText("What is the revenue trend for Q3?")).not.toBeVisible();
    // Switch to all
    await page.getByRole("button", { name: "all" }).click();
    await expect(page.getByText("What is the revenue trend for Q3?")).toBeVisible();
    await expect(page.getByText("Missing cost center mapping for EMEA")).toBeVisible();
  });

  test("task card shows status badge, source, and confidence", async ({ page }) => {
    await page.goto("/enrichment");
    const card = page.locator("li").first();
    await expect(card.getByText("open")).toBeVisible();
    await expect(card.getByText(/source: query/i)).toBeVisible();
    await expect(card.getByText(/45%/)).toBeVisible();
  });

  test("task card is a link to the task detail page", async ({ page }) => {
    await page.goto("/enrichment");
    await page.getByText("What is the revenue trend for Q3?").click();
    await page.waitForURL("**/enrichment/task-001");
  });

  test("shows empty state message when no tasks match filter", async ({ page }) => {
    await page.route("/api/v1/enrichment/tasks**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ api_version: "1", items: [], total: 0 }) })
    );
    await page.goto("/enrichment");
    await expect(page.getByText(/no open tasks/i)).toBeVisible();
  });

  test("shows error message on API failure", async ({ page }) => {
    await page.route("/api/v1/enrichment/tasks**", (route) =>
      route.fulfill({ status: 500, body: "Internal Server Error" })
    );
    await page.goto("/enrichment");
    await expect(page.getByText(/error/i)).toBeVisible();
  });
});
