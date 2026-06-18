import { test, expect } from "@playwright/test";

const TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZXYtYW5hbHlzdCIsInJvbGVzIjpbImFuYWx5c3QiXSwiZXhwIjo5OTk5OTk5OTk5fQ.fake";

const TASK = {
  task_id: "task-001",
  question_text: "What is the revenue trend for Q3?",
  confidence_score: 0.45,
  source: "query",
  status: "open",
  submitted_by: "dev-analyst",
  created_at: "2026-06-01T10:00:00Z",
};

test.describe("Task detail page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.evaluate((t) => localStorage.setItem("kdaf_token", t), TOKEN);

    // Task list used to resolve the task from taskId
    await page.route("/api/v1/enrichment/tasks**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ api_version: "1", items: [TASK], total: 1 }),
      })
    );
  });

  test("renders back link, question text, and split panel", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await expect(page.getByText(/← Tasks/i)).toBeVisible();
    await expect(page.getByText("What is the revenue trend for Q3?").first()).toBeVisible();
    await expect(page.getByText(/KG Write-back/i)).toBeVisible();
  });

  test("back link navigates to /enrichment", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await page.getByText(/← Tasks/i).click();
    await page.waitForURL("**/enrichment");
  });

  test("write-back panel: Preview button disabled when textarea is empty", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await expect(page.getByRole("button", { name: /preview/i })).toBeDisabled();
  });

  test("write-back panel: Preview button enabled after typing Cypher", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R001'}) SET r.description = 'test'");
    await expect(page.getByRole("button", { name: /preview/i })).toBeEnabled();
  });

  test("write-back panel: Preview shows the typed Cypher before commit", async ({ page }) => {
    const cypher = "MERGE (r:BusinessRule {id: 'R001'}) SET r.description = 'test'";
    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill(cypher);
    await page.getByRole("button", { name: /preview/i }).click();
    await expect(page.getByText("Review before committing:")).toBeVisible();
    await expect(page.getByText(cypher)).toBeVisible();
    await expect(page.getByRole("button", { name: /commit to kg/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /edit/i })).toBeVisible();
  });

  test("write-back panel: Edit button returns to textarea", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R1'}) SET r.x = 1");
    await page.getByRole("button", { name: /preview/i }).click();
    await page.getByRole("button", { name: /edit/i }).click();
    await expect(page.getByPlaceholder(/MERGE/i)).toBeVisible();
  });

  test("write-back panel: successful commit shows element_id and resolved state", async ({ page }) => {
    await page.route("/api/v1/graph/write", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ api_version: "1", element_id: "4:abc123:0" }),
      })
    );
    await page.route("/api/v1/enrichment/tasks/task-001", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...TASK, status: "resolved" }),
      })
    );

    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R001'}) SET r.description = 'test'");
    await page.getByRole("button", { name: /preview/i }).click();
    await page.getByRole("button", { name: /commit to kg/i }).click();
    await expect(page.getByText(/4:abc123:0/)).toBeVisible();
    await expect(page.getByText(/task resolved/i)).toBeVisible();
  });

  test("write-back panel: API error shows error message", async ({ page }) => {
    await page.route("/api/v1/graph/write", (route) =>
      route.fulfill({ status: 400, body: JSON.stringify({ detail: "Write guard: label not allowed" }) })
    );

    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R001'}) SET r.description = 'test'");
    await page.getByRole("button", { name: /preview/i }).click();
    await page.getByRole("button", { name: /commit to kg/i }).click();
    await expect(page.getByText(/error/i)).toBeVisible();
  });

  test("commit button disabled while request is in flight", async ({ page }) => {
    let resolve: () => void;
    const blocker = new Promise<void>((r) => { resolve = r; });
    await page.route("/api/v1/graph/write", async (route) => {
      await blocker;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ api_version: "1", element_id: "4:x:0" }) });
    });

    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R001'}) SET r.description = 'test'");
    await page.getByRole("button", { name: /preview/i }).click();
    await page.getByRole("button", { name: /commit to kg/i }).click();
    await expect(page.getByRole("button", { name: /committing/i })).toBeDisabled();
    resolve!();
  });

  test("chat panel renders welcome message and composer input", async ({ page }) => {
    await page.goto("/enrichment/task-001");
    await expect(page.getByText(/This gap was triggered by/i)).toBeVisible();
    await expect(page.getByRole("textbox", { name: /message input/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /send message/i })).toBeVisible();
  });

  // ── chat streaming (native AI SDK) ──────────────────────────────────────────

  // Helpers: build the UIMessageChunk SSE body that the BFF /api/chat emits.
  // The transport validates the x-vercel-ai-ui-message-stream header.
  const AI_SDK_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "x-vercel-ai-ui-message-stream": "v1",
  };

  function sseBody(chunks: object[]): string {
    return chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join("");
  }

  test("sending a message calls /api/chat and renders tool steps + final answer", async ({ page }) => {
    await page.route("/api/chat", (route) =>
      route.fulfill({
        status: 200,
        headers: AI_SDK_HEADERS,
        body: sseBody([
          { type: "tool-input-available", toolCallId: "n1", toolName: "check_cache", input: {}, dynamic: true },
          { type: "tool-output-available", toolCallId: "n1", output: "cache miss", dynamic: true },
          { type: "tool-input-available", toolCallId: "n2", toolName: "refiner", input: {}, dynamic: true },
          { type: "tool-output-available", toolCallId: "n2", output: "3 terms; no solver", dynamic: true },
          { type: "text-start", id: "t1" },
          { type: "text-delta", id: "t1", delta: "Revenue grew 12% in Q3." },
          { type: "text-end", id: "t1" },
        ]),
      })
    );

    await page.goto("/enrichment/task-001");
    await page.getByRole("textbox", { name: /message input/i }).fill("What is the revenue trend?");
    await page.getByRole("button", { name: /send message/i }).click();

    // Native tool step renders as "Used tool: <node>" — not inline markdown
    await expect(page.getByText(/used tool/i).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText(/check_cache/i)).toBeVisible();
    await expect(page.getByText("Revenue grew 12% in Q3.")).toBeVisible();
  });

  test("node progress does not appear as inline markdown *[node]* text", async ({ page }) => {
    await page.route("/api/chat", (route) =>
      route.fulfill({
        status: 200,
        headers: AI_SDK_HEADERS,
        body: sseBody([
          { type: "tool-input-available", toolCallId: "n1", toolName: "refiner", input: {}, dynamic: true },
          { type: "tool-output-available", toolCallId: "n1", output: "refined", dynamic: true },
          { type: "text-start", id: "t1" },
          { type: "text-delta", id: "t1", delta: "Final answer." },
          { type: "text-end", id: "t1" },
        ]),
      })
    );

    await page.goto("/enrichment/task-001");
    await page.getByRole("textbox", { name: /message input/i }).fill("test");
    await page.getByRole("button", { name: /send message/i }).click();

    await expect(page.getByText("Final answer.")).toBeVisible({ timeout: 8000 });
    // The old adapter injected *[refiner]* as markdown — this must not appear
    await expect(page.getByText(/\*\[refiner\]\*/)).not.toBeVisible();
  });

  test("chat error from backend renders error state", async ({ page }) => {
    await page.route("/api/chat", (route) =>
      route.fulfill({
        status: 200,
        headers: AI_SDK_HEADERS,
        body: sseBody([{ type: "error", errorText: "Backend unavailable" }]),
      })
    );

    await page.goto("/enrichment/task-001");
    await page.getByRole("textbox", { name: /message input/i }).fill("test");
    await page.getByRole("button", { name: /send message/i }).click();

    await expect(page.getByText(/backend unavailable/i)).toBeVisible({ timeout: 8000 });
  });

  test("shows resolved banner after successful commit instead of write-back panel", async ({ page }) => {
    await page.route("/api/v1/graph/write", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ api_version: "1", element_id: "4:z:0" }) })
    );
    await page.route("/api/v1/enrichment/tasks/task-001", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...TASK, status: "resolved" }) })
    );

    await page.goto("/enrichment/task-001");
    await page.getByPlaceholder(/MERGE/i).fill("MERGE (r:BusinessRule {id: 'R001'}) SET r.x = 1");
    await page.getByRole("button", { name: /preview/i }).click();
    await page.getByRole("button", { name: /commit to kg/i }).click();
    await expect(page.getByText(/Return to the task list/i)).toBeVisible();
  });
});
