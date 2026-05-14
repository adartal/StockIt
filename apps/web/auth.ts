import NextAuth from "next-auth";
import { jwtVerify } from "jose";

import {
  SESSION_MAX_AGE_SECONDS,
  isEmailAllowed,
  mintSessionToken,
} from "@/lib/magic-link";

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
      const email = typeof token.email === "string" ? token.email : null;
      if (!email) {
        throw new Error("Session token missing email");
      }
      return await mintSessionToken(email, maxAge ?? SESSION_MAX_AGE_SECONDS);
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
  providers: [],
  pages: {
    signIn: "/login",
    verifyRequest: "/login?check=email",
  },
  callbacks: {
    async signIn({ user }) {
      const email = user.email?.toLowerCase();
      if (!email) return false;
      return isEmailAllowed(email);
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
