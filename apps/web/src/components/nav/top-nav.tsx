import Link from "next/link";

import { signOut } from "../../../auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

const links = [
  { href: "/", label: "Brief" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/settings", label: "Rules" },
];

function initialFor(email?: string | null): string {
  if (!email) return "·";
  const c = email.trim()[0];
  return c ? c.toUpperCase() : "·";
}

export function TopNav({ email }: { email?: string | null }) {
  return (
    <header
      data-app-nav
      className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-md print:hidden"
    >
      <nav className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 py-3">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="group flex items-baseline gap-2"
            aria-label="StockIt home"
          >
            <span className="font-display text-2xl font-medium tracking-tight">
              StockIt
            </span>
            <span className="hidden text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground sm:inline">
              — analyst desk
            </span>
          </Link>
          <ul className="flex items-center gap-1 text-sm">
            {links.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className="rounded-md px-2.5 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {email ? (
            <span
              aria-label={email}
              title={email}
              className="hidden h-8 w-8 select-none items-center justify-center rounded-full border border-border bg-card font-mono text-xs uppercase text-muted-foreground sm:inline-flex"
            >
              {initialFor(email)}
            </span>
          ) : null}
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <Button
              type="submit"
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-foreground"
            >
              Sign out
            </Button>
          </form>
        </div>
      </nav>
    </header>
  );
}
