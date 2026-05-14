import { test, expect } from "./fixtures";

/**
 * Add to watchlist → refresh → see "Changed" badge.
 *
 * Flow:
 *   1. Visit /watchlist and add a ticker (uses a unique-per-run name so
 *      reruns against a persisted DB don't collide on a unique constraint).
 *   2. Reload the page once — this seeds the localStorage "lastSeen"
 *      timestamp for the new item (the first sighting never badges).
 *   3. Click "Refresh now" → the server updates `updated_at`.
 *   4. Reload — the row should now show the "Changed" badge.
 *
 * Like plan-submit, this exercises the live backend.
 */

function uniqueTicker(): string {
  // 4 random uppercase letters; the input form forbids non-letters and the
  // watchlist add path forwards to the backend which accepts any 1–16 chars.
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let s = "";
  for (let i = 0; i < 4; i++) s += letters[Math.floor(Math.random() * letters.length)];
  return s;
}

test("add to watchlist, refresh, reload, see Changed badge", async ({
  authedContext,
}) => {
  test.setTimeout(180_000);

  const page = await authedContext.newPage();
  const ticker = uniqueTicker();

  await page.goto("/watchlist");
  await expect(
    page.getByRole("heading", { name: /watchlist/i }),
  ).toBeVisible();

  await page.getByLabel(/ticker/i).fill(ticker);
  await page.getByRole("button", { name: /add ticker/i }).click();

  const row = page.locator("tr", { hasText: ticker });
  await expect(row).toBeVisible({ timeout: 15_000 });

  // First sighting seeds lastSeen — reload so the next refresh registers as
  // a change against a known prior timestamp.
  await page.reload();
  await expect(page.locator("tr", { hasText: ticker })).toBeVisible();
  await expect(
    page.locator("tr", { hasText: ticker }).getByText(/changed/i),
  ).toHaveCount(0);

  await page
    .locator("tr", { hasText: ticker })
    .getByRole("button", { name: /refresh now/i })
    .click();

  // The refresh action revalidates and the table re-renders with a newer
  // `updated_at`. Reload to clear any in-flight transition state and check
  // for the badge.
  await page.waitForTimeout(2000);
  await page.reload();
  const changedBadge = page
    .locator("tr", { hasText: ticker })
    .getByText(/changed/i);
  await expect(changedBadge).toBeVisible({ timeout: 30_000 });
});
