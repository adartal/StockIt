import { test, expect } from "@playwright/test";

/**
 * Login flow:
 *   - Unauthenticated visit to `/` redirects to `/login`.
 *   - The login page renders the email form.
 *   - Submitting an email kicks off the magic-link flow and redirects to
 *     `?check=email`. We don't actually open the mailbox here — that's
 *     covered by the manual verification step in v1-acceptance.md.
 */

test("unauthenticated user is redirected to /login", async ({ page }) => {
  const response = await page.goto("/");
  // Middleware redirects → final URL should be /login (possibly with params).
  await expect(page).toHaveURL(/\/login(\?.*)?$/);
  expect(response?.ok()).toBeTruthy();

  await expect(
    page.getByRole("heading", { name: /stockit/i }),
  ).toBeVisible();
  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /magic link/i })).toBeVisible();
});

test("submitting the form transitions to the check-email state", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("e2e@stockit.local");
  await page.getByRole("button", { name: /magic link/i }).click();

  // The Resend provider in Next-Auth redirects to the verifyRequest page,
  // which is `/login?check=email`. Allow either the URL update or the inline
  // success banner — both signal the magic-link request was accepted.
  await expect(async () => {
    const url = page.url();
    const bannerVisible = await page
      .getByText(/check your email/i)
      .isVisible()
      .catch(() => false);
    expect(/check=email/.test(url) || bannerVisible).toBeTruthy();
  }).toPass({ timeout: 15_000 });
});
