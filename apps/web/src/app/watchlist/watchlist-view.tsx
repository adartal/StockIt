"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import type { WatchlistItem } from "@/lib/api-types";
import {
  addWatchlistItem,
  deleteWatchlistItem,
  refreshWatchlistItem,
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
    /* quota or disabled — ignore */
  }
}

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function WatchlistView({
  initialItems,
}: {
  initialItems: WatchlistItem[];
}) {
  const [items] = useState(initialItems);
  // Snapshot the *previous* visit's lastSeen map on first client render. Lazy
  // init keeps it stable across re-renders so badges don't flicker after the
  // commit-time write-back below. SSR returns {} (no window) and hydration
  // recomputes on mount.
  const [lastSeen] = useState<LastSeenMap>(() => readLastSeen());
  const [error, setError] = useState<string | null>(null);
  const [ticker, setTicker] = useState("");
  const [pending, startTransition] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);

  // After render, persist the current items' updated_at so the next visit can
  // detect changes since now.
  useEffect(() => {
    const next: LastSeenMap = { ...readLastSeen() };
    for (const item of initialItems) {
      next[item.id] = item.updated_at;
    }
    writeLastSeen(next);
  }, [initialItems]);

  function hasChanged(item: WatchlistItem): boolean {
    const seen = lastSeen[item.id];
    if (!seen) return false; // first time we see this item → don't badge it
    return new Date(item.updated_at).getTime() > new Date(seen).getTime();
  }

  function handleAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      const res = await addWatchlistItem(fd);
      if (!res.ok) setError(res.error);
      else setTicker("");
    });
  }

  function handleRefresh(id: string) {
    setError(null);
    setBusyId(id);
    startTransition(async () => {
      const res = await refreshWatchlistItem(id);
      if (!res.ok) setError(res.error);
      setBusyId(null);
    });
  }

  function handleDelete(id: string) {
    setError(null);
    setBusyId(id);
    startTransition(async () => {
      const res = await deleteWatchlistItem(id);
      if (!res.ok) setError(res.error);
      setBusyId(null);
    });
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleAdd}
        className="flex items-end gap-3 rounded-lg border border-border p-4"
      >
        <div className="flex-1">
          <label
            htmlFor="ticker"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            Ticker
          </label>
          <input
            id="ticker"
            name="ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="AAPL"
            required
            maxLength={16}
            className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>
        <Button type="submit" disabled={pending || !ticker.trim()}>
          Add ticker
        </Button>
      </form>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-2 text-left">Ticker</th>
              <th className="px-4 py-2 text-left">Last refreshed</th>
              <th className="px-4 py-2 text-left">Last plan</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="px-4 py-8 text-center text-muted-foreground"
                >
                  No tickers yet. Add one above.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-border">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{item.ticker}</span>
                      {hasChanged(item) ? (
                        <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
                          Changed
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {fmt(item.updated_at)}
                  </td>
                  <td className="px-4 py-3">
                    {item.last_plan_id ? (
                      <Link
                        href={`/plans/${item.last_plan_id}`}
                        className="text-primary underline-offset-4 hover:underline"
                      >
                        View plan
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={pending && busyId === item.id}
                        onClick={() => handleRefresh(item.id)}
                      >
                        {pending && busyId === item.id
                          ? "Refreshing…"
                          : "Refresh now"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={pending && busyId === item.id}
                        onClick={() => handleDelete(item.id)}
                      >
                        Remove
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
