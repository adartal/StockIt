import type { WatchlistItem } from "@/lib/api";

const MIN_ITEMS = 6;

export function Tickertape({ items }: { items: WatchlistItem[] }) {
  if (items.length < MIN_ITEMS) return null;

  const doubled = [...items, ...items];

  return (
    <div
      aria-hidden
      className="overflow-hidden border-y border-border bg-card/40 [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]"
    >
      <div className="animate-ticker flex w-max items-center py-1.5 font-mono text-[11px] tracking-wide text-muted-foreground">
        {doubled.map((it, i) => (
          <span
            key={`${it.id}-${i}`}
            className="flex items-center whitespace-nowrap"
          >
            <span className="px-6 text-foreground">{it.ticker}</span>
            <span
              aria-hidden
              className="h-3 w-px bg-border opacity-60"
            />
          </span>
        ))}
      </div>
    </div>
  );
}
