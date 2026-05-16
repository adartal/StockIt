"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import {
  ArrowRightIcon,
  CircleDotIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCcwIcon,
  TrashIcon,
} from "lucide-react";

import { Sparkline } from "@/components/charts/Sparkline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { WatchlistItem } from "@/lib/api";
import {
  addWatchlistAction,
  deleteWatchlistAction,
  refreshWatchlistAction,
} from "./actions";

const LS_KEY = "stockit:watchlist:lastSeen";

type LastSeenMap = Record<string, string>;

function readLastSeen(): LastSeenMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as LastSeenMap) : {};
  } catch {
    return {};
  }
}

function writeLastSeen(map: LastSeenMap) {
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

function ago(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function WatchlistView({
  initialItems,
}: {
  initialItems: WatchlistItem[];
}) {
  const items = initialItems;
  const [lastSeen] = useState<LastSeenMap>(() => readLastSeen());
  const [error, setError] = useState<string | null>(null);
  const [ticker, setTicker] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [pending, startTransition] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const next: LastSeenMap = { ...readLastSeen() };
    for (const item of initialItems) {
      next[item.id] = item.updated_at;
    }
    writeLastSeen(next);
  }, [initialItems]);

  function hasChanged(item: WatchlistItem): boolean {
    const seen = lastSeen[item.id];
    if (!seen) return false;
    return new Date(item.updated_at).getTime() > new Date(seen).getTime();
  }

  function handleAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      const res = await addWatchlistAction(fd);
      if (!res.ok) setError(res.error);
      else {
        setTicker("");
        setShowAdd(false);
      }
    });
  }

  function handleRefresh(id: string) {
    setError(null);
    setBusyId(id);
    startTransition(async () => {
      const res = await refreshWatchlistAction(id);
      if (!res.ok) setError(res.error);
      setBusyId(null);
    });
  }

  function handleDelete(id: string) {
    setError(null);
    setBusyId(id);
    startTransition(async () => {
      const res = await deleteWatchlistAction(id);
      if (!res.ok) setError(res.error);
      setBusyId(null);
    });
  }

  return (
    <div className="space-y-8">
      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {items.map((item) => {
            const changed = hasChanged(item);
            const busy = pending && busyId === item.id;
            return (
              <li
                key={item.id}
                className={cn(
                  "group grid gap-4 py-5 sm:grid-cols-[140px_1fr_auto] sm:items-center",
                  changed && "relative",
                )}
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-display text-3xl font-medium tracking-tight">
                    {item.ticker}
                  </span>
                  {changed ? (
                    <CircleDotIcon
                      className="size-2.5 animate-signal-pulse text-amber-signal"
                      strokeWidth={2.5}
                    />
                  ) : null}
                </div>

                <div className="space-y-1">
                  <Sparkline ticker={item.ticker} height={40} range="3mo" interval="1d" />
                  <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    <span>refreshed {ago(item.updated_at)}</span>
                    {item.last_plan_id ? (
                      <Link
                        href={`/plans/${item.last_plan_id}`}
                        className="group/lnk inline-flex items-center gap-1 text-foreground hover:text-primary"
                      >
                        Open brief
                        <ArrowRightIcon
                          className="size-3 transition-transform group-hover/lnk:translate-x-0.5"
                          strokeWidth={1.5}
                        />
                      </Link>
                    ) : null}
                  </div>
                </div>

                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => handleRefresh(item.id)}
                    aria-label={`Refresh ${item.ticker}`}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    {busy ? (
                      <Loader2Icon className="size-4 animate-spin" strokeWidth={1.5} />
                    ) : (
                      <RefreshCcwIcon className="size-4" strokeWidth={1.5} />
                    )}
                    <span className="hidden sm:inline">Refresh</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => handleDelete(item.id)}
                    aria-label={`Remove ${item.ticker}`}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <TrashIcon className="size-4" strokeWidth={1.5} />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {showAdd ? (
        <form
          onSubmit={handleAdd}
          className="flex items-end gap-3 rounded-lg border border-border bg-card p-4"
        >
          <div className="flex-1">
            <Label
              htmlFor="watchlist-ticker"
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
            >
              Track a ticker
            </Label>
            <Input
              id="watchlist-ticker"
              name="ticker"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="AAPL"
              required
              maxLength={16}
              autoFocus
              className="mt-1 h-auto rounded-none border-0 border-b border-input bg-transparent px-0 font-display text-2xl tracking-tight focus-visible:border-primary focus-visible:ring-0"
            />
          </div>
          <Button type="submit" disabled={pending || !ticker.trim()}>
            Add
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setShowAdd(false)}
            disabled={pending}
          >
            Cancel
          </Button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="group inline-flex items-center gap-2 rounded-full border border-dashed border-border bg-transparent px-4 py-2 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-primary"
        >
          <PlusIcon className="size-4" strokeWidth={1.5} />
          Track a ticker
        </button>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
      <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
        Nothing on watch
      </p>
      <h2 className="mt-3 font-display text-3xl font-medium tracking-tight">
        A blank board.
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Brief a plan from the home page, then add the ticker here to follow it.
        We&rsquo;ll surface changes since your last visit.
      </p>
    </div>
  );
}
