import { auth } from "./auth";

export default auth((req) => {
  const { pathname } = req.nextUrl;

  if (
    pathname.startsWith("/login") ||
    pathname.startsWith("/api/auth")
  ) {
    return;
  }

  if (!req.auth) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    return Response.redirect(loginUrl);
  }
});

export const config = {
  // Run on every path except Next internals and static assets. The callback
  // itself whitelists /login and /api/auth so they remain reachable.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
