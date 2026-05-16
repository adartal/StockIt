import Link from "next/link";
import { ArrowRightIcon, CircleDotIcon, EyeIcon } from "lucide-react";

import { Sparkline } from "@/components/charts/Sparkline";
import type { WatchlistItem } from "@/lib/api";

function ago(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function WatchlistPreview({ items }: { items: WatchlistItem[] }) {
  const top = items.slice(0, 5);

  return (
    <aside className="space-y-4 rounded-xl border border-border bg-card/60 p-5 backdrop-blur-sm">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <EyeIcon className="size-3.5 text-muted-foreground" strokeWidth={1.5} />
          <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-foreground">
            On watch
          </h2>
        </div>
        <Link
          href="/watchlist"
          className="group flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
        >
          All
          <ArrowRightIcon className="size-3 transition-transform group-hover:translate-x-0.5" strokeWidth={1.5} />
        </Link>
      </header>

      {top.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          Nothing on watch yet.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {top.map((it) => (
            <li key={it.id} className="py-3 first:pt-0 last:pb-0">
              <div className="flex items-center justify-between gap-3">
                <Link
                  href={it.last_plan_id ? `/plans/${it.last_plan_id}` : "/watchlist"}
                  className="group flex items-baseline gap-2"
                >
                  <span className="font-display text-xl font-medium tracking-tight group-hover:text-primary">
                    {it.ticker}
                  </span>
                  <CircleDotIcon className="size-2 text-amber-signal" strokeWidth={2} />
                </Link>
                <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  {ago(it.updated_at)}
                </span>
              </div>
              <div className="mt-1.5">
                <Sparkline ticker={it.ticker} height={28} range="3mo" interval="1d" />
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
