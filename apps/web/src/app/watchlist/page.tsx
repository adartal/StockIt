import { listWatchlist, type WatchlistItem } from "@/lib/api";
import { WatchlistView } from "./watchlist-view";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  let items: WatchlistItem[] = [];
  let error: string | null = null;
  try {
    items = await listWatchlist();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load watchlist";
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
      <header className="mb-10 space-y-3 border-b border-border pb-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Tracked
        </p>
        <div className="flex items-end justify-between gap-4">
          <h1 className="font-display text-5xl font-semibold leading-none tracking-tight">
            On watch
          </h1>
          <p className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {items.length} ticker{items.length === 1 ? "" : "s"}
          </p>
        </div>
        <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
          Tickers you&rsquo;re tracking. Refresh to regenerate the plan with
          new prices, news, and macro data — the amber dot tells you a row has
          moved since your last visit.
        </p>
      </header>
      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : (
        <WatchlistView initialItems={items} />
      )}
    </main>
  );
}
