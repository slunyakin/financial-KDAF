import { test, expect } from "@playwright/test";

const TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZXYtYW5hbHlzdCIsInJvbGVzIjpbImFuYWx5c3QiXSwiZXhwIjo5OTk5OTk5OTk5fQ.fake";

test.describe("Login page", () => {
  test.beforeEach(async ({ page }) => {
    // Clear auth state
    await page.goto("/login");
    await page.evaluate(() => localStorage.removeItem("kdaf_token"));
  });

  test("renders username and password fields and a submit button", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("shows inline error on 401", async ({ page }) => {
    await page.route("/api/v1/auth/token", (route) =>
      route.fulfill({ status: 401, body: JSON.stringify({ detail: "Invalid credentials" }) })
    );
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("bad-user");
    await page.getByLabel(/password/i).fill("wrong");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/invalid credentials/i)).toBeVisible();
  });

  test("stores token and redirects to /enrichment on success", async ({ page }) => {
    await page.route("/api/v1/auth/token", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: TOKEN, token_type: "bearer", expires_in: 86400 }),
      })
    );
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("dev-analyst");
    await page.getByLabel(/password/i).fill("devpass");
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL("**/enrichment");
    const stored = await page.evaluate(() => localStorage.getItem("kdaf_token"));
    expect(stored).toBe(TOKEN);
  });

  test("disables submit button while request is in flight", async ({ page }) => {
    let resolve: () => void;
    const blocker = new Promise<void>((r) => { resolve = r; });
    await page.route("/api/v1/auth/token", async (route) => {
      await blocker;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: TOKEN, expires_in: 86400 }) });
    });
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("dev-analyst");
    await page.getByLabel(/password/i).fill("devpass");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("button", { name: /signing in/i })).toBeDisabled();
    resolve!();
  });

  test("redirects to /enrichment if already authenticated", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate((t) => localStorage.setItem("kdaf_token", t), TOKEN);
    await page.goto("/login");
    await page.waitForURL("**/enrichment");
  });
});
