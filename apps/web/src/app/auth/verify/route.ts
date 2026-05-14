import { NextResponse, type NextRequest } from "next/server";

import {
  SESSION_MAX_AGE_SECONDS,
  isEmailAllowed,
  mintSessionToken,
  sessionCookieName,
  verifyMagicLinkToken,
} from "@/lib/magic-link";

export async function GET(request: NextRequest): Promise<Response> {
  const token = request.nextUrl.searchParams.get("token");
  const failure = NextResponse.redirect(new URL("/login?error=InvalidLink", request.nextUrl));

  if (!token) return failure;

  const email = await verifyMagicLinkToken(token);
  if (!email || !isEmailAllowed(email)) return failure;

  const sessionToken = await mintSessionToken(email);
  const response = NextResponse.redirect(new URL("/", request.nextUrl));
  response.cookies.set({
    name: sessionCookieName(request.nextUrl),
    value: sessionToken,
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
