import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for M10 E2E smoke tests.
 *
 * These tests expect:
 *   - `apps/api` running on http://localhost:8000
 *   - `apps/web` running on http://localhost:3000
 *   - `ALLOWED_EMAILS` includes `e2e@stockit.local`
 *
 * They DO NOT spin up the backend automatically — start it yourself before
 * running. Auth is bypassed by injecting a signed Auth.js JWT cookie via
 * `tests/e2e/fixtures.ts`.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: "list",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_WEB_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
