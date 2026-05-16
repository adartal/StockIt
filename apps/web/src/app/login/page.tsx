import { redirect } from "next/navigation";
import { headers } from "next/headers";
import { CircleAlertIcon, MailCheckIcon } from "lucide-react";

import {
  isEmailAllowed,
  mintMagicLinkToken,
  sendMagicLinkEmail,
} from "@/lib/magic-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type SearchParams = Promise<{ check?: string; error?: string }>;

function errorMessage(error: string | undefined): string | null {
  if (!error) return null;
  if (error === "AccessDenied") return "This email isn't on the allowlist.";
  if (error === "InvalidLink")
    return "That sign-in link is invalid or has expired. Request a new one below.";
  return "Sign-in failed. Please try again.";
}

async function originFromHeaders(): Promise<string> {
  const explicit = process.env.AUTH_URL;
  if (explicit) return explicit.replace(/\/$/, "");
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "http";
  if (!host) throw new Error("Cannot determine request origin");
  return `${proto}://${host}`;
}

const HERO_TICKERS = ["AAPL", "TSLA", "VOO", "NVDA", "SPY", "QQQ", "MSFT", "AMZN"];

export default async function LoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const checkEmail = params.check === "email";
  const error = errorMessage(params.error);

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.2fr_1fr]">
      {/* Hero */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-card px-12 py-14 lg:flex">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.05] [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]"
        >
          <div className="grid h-full grid-cols-4 gap-y-12 pt-24 font-display text-[14vw] font-medium leading-none tracking-tight">
            {HERO_TICKERS.map((t, i) => (
              <span
                key={t}
                className={i % 2 === 0 ? "text-foreground" : "text-primary"}
              >
                {t}
              </span>
            ))}
          </div>
        </div>

        <div className="relative space-y-2">
          <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
            StockIt — personal analyst desk
          </p>
          <span className="block size-2 rounded-full bg-primary" />
        </div>

        <div className="relative space-y-4">
          <h1 className="font-display text-6xl font-semibold leading-[0.95] tracking-tight text-balance">
            Brief a ticker.
            <br />
            <span className="text-primary">Get a plan.</span>
          </h1>
          <p className="max-w-md text-pretty text-sm leading-relaxed text-muted-foreground">
            A research desk for one. Fundamentals, technicals, news and macro —
            synthesized into entries, sizing, stops, catalysts and risk flags.
          </p>
        </div>

        <p className="relative font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          v.0 · for personal use
        </p>
      </aside>

      {/* Form */}
      <section className="flex flex-col items-center justify-center px-6 py-12 sm:px-12">
        <div className="w-full max-w-sm space-y-8">
          <header className="space-y-2 text-center lg:hidden">
            <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
              StockIt
            </p>
            <h2 className="font-display text-3xl font-medium tracking-tight">
              Sign in
            </h2>
          </header>

          <div className="space-y-2">
            <p className="hidden font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground lg:block">
              Sign in
            </p>
            <h2 className="hidden font-display text-3xl font-medium tracking-tight lg:block">
              Welcome back.
            </h2>
            <p className="text-sm text-muted-foreground">
              We&rsquo;ll email you a one-time magic link. No passwords.
            </p>
          </div>

          {checkEmail ? (
            <div className="flex items-start gap-2 rounded-md border border-bullish/40 bg-bullish/10 p-3 text-sm text-bullish">
              <MailCheckIcon className="mt-0.5 size-4" strokeWidth={1.5} />
              <span>
                Check your email for a sign-in link. It expires in 10 minutes.
              </span>
            </div>
          ) : null}

          {error ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
            >
              <CircleAlertIcon className="mt-0.5 size-4" strokeWidth={1.5} />
              <span>{error}</span>
            </div>
          ) : null}

          <form
            action={async (formData) => {
              "use server";
              const email = String(formData.get("email") ?? "").trim().toLowerCase();
              if (email && isEmailAllowed(email)) {
                const origin = await originFromHeaders();
                const token = await mintMagicLinkToken(email);
                const url = `${origin}/auth/verify?token=${encodeURIComponent(token)}`;
                try {
                  await sendMagicLinkEmail(email, url);
                } catch (err) {
                  console.error("[login] sendMagicLinkEmail failed", err);
                }
              }
              redirect("/login?check=email");
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label
                htmlFor="email"
                className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
              >
                Email
              </Label>
              <Input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="you@example.com"
                className="h-auto rounded-none border-0 border-b border-input bg-transparent px-0 py-2 text-lg focus-visible:border-primary focus-visible:ring-0"
              />
            </div>
            <Button type="submit" className="w-full" size="lg">
              Send magic link
            </Button>
          </form>

          <p className="border-t border-border pt-4 text-center text-xs text-muted-foreground">
            Access is limited to allowlisted email addresses.
          </p>
        </div>
      </section>
    </main>
  );
}
