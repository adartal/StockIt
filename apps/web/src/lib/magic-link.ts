import { SignJWT, jwtVerify } from "jose";
import { Resend } from "resend";

const ALG = "HS256";
const MAGIC_LINK_PURPOSE = "magic-link";

export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days
export const MAGIC_LINK_MAX_AGE_SECONDS = 60 * 10; // 10 minutes

function authSecret(): Uint8Array {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error("AUTH_SECRET is not set");
  }
  return new TextEncoder().encode(secret);
}

export function allowedEmails(): Set<string> {
  const raw = process.env.ALLOWED_EMAILS ?? "";
  return new Set(
    raw
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isEmailAllowed(email: string): boolean {
  const allow = allowedEmails();
  if (allow.size === 0) return false;
  return allow.has(email.toLowerCase());
}

export async function mintSessionToken(
  email: string,
  maxAgeSeconds: number = SESSION_MAX_AGE_SECONDS,
): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const normalized = email.toLowerCase();
  return await new SignJWT({ email: normalized, sub: normalized })
    .setProtectedHeader({ alg: ALG, typ: "JWT" })
    .setIssuedAt(now)
    .setExpirationTime(now + maxAgeSeconds)
    .sign(authSecret());
}

export async function mintMagicLinkToken(email: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return await new SignJWT({
    email: email.toLowerCase(),
    purpose: MAGIC_LINK_PURPOSE,
  })
    .setProtectedHeader({ alg: ALG, typ: "JWT" })
    .setIssuedAt(now)
    .setExpirationTime(now + MAGIC_LINK_MAX_AGE_SECONDS)
    .sign(authSecret());
}

export async function verifyMagicLinkToken(token: string): Promise<string | null> {
  try {
    const { payload } = await jwtVerify(token, authSecret(), {
      algorithms: [ALG],
    });
    if (payload.purpose !== MAGIC_LINK_PURPOSE) return null;
    const email = payload.email;
    if (typeof email !== "string" || !email.includes("@")) return null;
    return email.toLowerCase();
  } catch {
    return null;
  }
}

export async function sendMagicLinkEmail(email: string, url: string): Promise<void> {
  const apiKey = process.env.AUTH_RESEND_KEY ?? process.env.RESEND_API_KEY;
  const from = process.env.AUTH_EMAIL_FROM ?? process.env.EMAIL_FROM;
  if (!apiKey) throw new Error("AUTH_RESEND_KEY is not set");
  if (!from) throw new Error("AUTH_EMAIL_FROM is not set");

  const resend = new Resend(apiKey);
  const escapedUrl = url.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const result = await resend.emails.send({
    from,
    to: email,
    subject: "Sign in to StockIt",
    html: `<!doctype html>
<html><body style="font-family:system-ui,sans-serif;line-height:1.5;padding:24px">
  <p>Click the link below to sign in to StockIt. The link expires in 10 minutes.</p>
  <p><a href="${escapedUrl}" style="display:inline-block;padding:10px 16px;background:#111;color:#fff;border-radius:6px;text-decoration:none">Sign in</a></p>
  <p style="color:#666;font-size:12px">If the button doesn't work, paste this URL into your browser:<br>${escapedUrl}</p>
  <p style="color:#666;font-size:12px">If you didn't request this email, you can ignore it.</p>
</body></html>`,
    text: `Sign in to StockIt: ${url}\n\nThe link expires in 10 minutes. If you didn't request it, ignore this email.`,
  });
  if (result.error) {
    throw new Error(`Resend send failed: ${result.error.message ?? String(result.error)}`);
  }
}

export function sessionCookieName(requestUrl: string | URL): string {
  const url = typeof requestUrl === "string" ? new URL(requestUrl) : requestUrl;
  return url.protocol === "https:"
    ? "__Secure-authjs.session-token"
    : "authjs.session-token";
}
