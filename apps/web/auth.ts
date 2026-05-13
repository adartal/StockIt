import NextAuth from "next-auth";
import Resend from "next-auth/providers/resend";
import { SignJWT, jwtVerify } from "jose";

const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

function allowedEmails(): Set<string> {
  const raw = process.env.ALLOWED_EMAILS ?? "";
  return new Set(
    raw
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

function authSecret(): Uint8Array {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error("AUTH_SECRET is not set");
  }
  return new TextEncoder().encode(secret);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  secret: process.env.AUTH_SECRET,
  session: {
    strategy: "jwt",
    maxAge: SESSION_MAX_AGE_SECONDS,
  },
  // Override the default JWE-encrypted token with an HS256-signed JWT so the
  // FastAPI backend can verify it with the same AUTH_SECRET.
  jwt: {
    maxAge: SESSION_MAX_AGE_SECONDS,
    async encode({ token, maxAge }) {
      if (!token) {
        throw new Error("Missing token to encode");
      }
      const now = Math.floor(Date.now() / 1000);
      const exp = now + (maxAge ?? SESSION_MAX_AGE_SECONDS);
      return await new SignJWT({ ...token })
        .setProtectedHeader({ alg: "HS256", typ: "JWT" })
        .setIssuedAt(now)
        .setExpirationTime(exp)
        .sign(authSecret());
    },
    async decode({ token }) {
      if (!token) return null;
      try {
        const { payload } = await jwtVerify(token, authSecret(), {
          algorithms: ["HS256"],
        });
        return payload as Record<string, unknown>;
      } catch {
        return null;
      }
    },
  },
  providers: [
    Resend({
      apiKey: process.env.AUTH_RESEND_KEY ?? process.env.RESEND_API_KEY,
      from: process.env.AUTH_EMAIL_FROM ?? process.env.EMAIL_FROM,
    }),
  ],
  pages: {
    signIn: "/login",
    verifyRequest: "/login?check=email",
  },
  callbacks: {
    async signIn({ user }) {
      const email = user.email?.toLowerCase();
      if (!email) return false;
      const allow = allowedEmails();
      if (allow.size === 0) return false;
      return allow.has(email);
    },
    async jwt({ token, user }) {
      if (user?.email) {
        token.email = user.email.toLowerCase();
        token.sub = token.email;
      }
      return token;
    },
    async session({ session, token }) {
      if (token?.email && session.user) {
        session.user.email = String(token.email);
      }
      return session;
    },
  },
});
