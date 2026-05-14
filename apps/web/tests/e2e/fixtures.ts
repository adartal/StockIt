/**
 * Test fixtures: authenticated browser context with an Auth.js session cookie.
 *
 * Avoids exercising the magic-link flow in every spec by minting a signed
 * HS256 JWT (same scheme as `apps/web/auth.ts`) and writing it directly as
 * the Auth.js session cookie. The login spec still drives the real form.
 */

import { test as base, expect, type BrowserContext } from "@playwright/test";
import { SignJWT } from "jose";

const SESSION_COOKIE_NAME =
  process.env.AUTH_URL?.startsWith("https://") || process.env.E2E_WEB_URL?.startsWith("https://")
    ? "__Secure-authjs.session-token"
    : "authjs.session-token";

export const TEST_USER_EMAIL = process.env.E2E_USER_EMAIL ?? "e2e@stockit.local";

async function mintSessionCookie(): Promise<string> {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error(
      "AUTH_SECRET must be set in the Playwright env to mint a session cookie",
    );
  }
  const key = new TextEncoder().encode(secret);
  const now = Math.floor(Date.now() / 1000);
  const exp = now + 60 * 60; // 1h
  return new SignJWT({ email: TEST_USER_EMAIL, sub: TEST_USER_EMAIL })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuedAt(now)
    .setExpirationTime(exp)
    .sign(key);
}

export async function seedAuthCookie(
  context: BrowserContext,
  baseURL: string,
): Promise<void> {
  const url = new URL(baseURL);
  const token = await mintSessionCookie();
  await context.addCookies([
    {
      name: SESSION_COOKIE_NAME,
      value: token,
      domain: url.hostname,
      path: "/",
      httpOnly: true,
      secure: url.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
}

type AuthedFixtures = {
  authedContext: BrowserContext;
};

export const test = base.extend<AuthedFixtures>({
  authedContext: async ({ browser, baseURL }, use) => {
    const context = await browser.newContext();
    await seedAuthCookie(context, baseURL ?? "http://localhost:3000");
    await use(context);
    await context.close();
  },
});

export { expect };
