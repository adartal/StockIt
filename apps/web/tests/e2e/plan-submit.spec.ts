import { test, expect } from "./fixtures";

/**
 * Submit form → see plan.
 *
 * Uses the authed context fixture so we skip the magic-link flow. Submits
 * the plan-input form for AAPL / $10,000 / swing and waits for the
 * navigation to `/plans/<uuid>` plus the rendered plan title.
 *
 * This spec needs the FastAPI backend reachable from the Next.js server and
 * configured with at least one LLM key. Plan generation can take ~60s.
 */

test("submitting the input form generates a plan and renders it", async ({
  authedContext,
}) => {
  test.setTimeout(180_000);

  const page = await authedContext.newPage();
  await page.goto("/");
  await expect(page).toHaveURL("/");
  await expect(
    page.getByRole("heading", { name: /new trading plan/i }),
  ).toBeVisible();

  await page.getByLabel(/ticker/i).fill("AAPL");
  await page.getByLabel(/capital/i).fill("10000");
  await page.getByLabel("Swing", { exact: false }).check();

  await page.getByRole("button", { name: /generate plan/i }).click();

  // Navigation to /plans/<id> is the success signal. Wait generously — real
  // synthesis with live LLMs is the slow path.
  await page.waitForURL(/\/plans\/[0-9a-f-]{36}/, { timeout: 150_000 });
  await expect(page.getByText(/AAPL/i).first()).toBeVisible();
  await expect(page.getByText(/swing/i).first()).toBeVisible();
});
