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
    <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Watchlist</h1>
          <p className="text-sm text-muted-foreground">
            Tickers you track. Refresh to generate a new plan revision.
          </p>
        </div>
      </div>
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
