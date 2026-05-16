"use client";

import { useEffect, useState } from "react";

interface Quote {
  ticker: string;
  label: string;
  close: number | null;
  change: number | null;
}

const TICKERS: { ticker: string; label: string }[] = [
  { ticker: "SPY", label: "S&P 500" },
  { ticker: "QQQ", label: "Nasdaq 100" },
  { ticker: "IWM", label: "Russell 2000" },
  { ticker: "TLT", label: "Long Bonds" },
  { ticker: "GLD", label: "Gold" },
];

async function fetchQuote(ticker: string): Promise<Quote> {
  try {
    const res = await fetch(
      `/api/prices?ticker=${encodeURIComponent(ticker)}&range=5d&interval=1d`,
    );
    if (!res.ok) return { ticker, label: ticker, close: null, change: null };
    const data = (await res.json()) as { bars: { close: number }[] };
    const bars = data.bars ?? [];
    if (bars.length < 2) return { ticker, label: ticker, close: null, change: null };
    const last = bars[bars.length - 1].close;
    const prev = bars[bars.length - 2].close;
    return {
      ticker,
      label: ticker,
      close: last,
      change: (last - prev) / prev,
    };
  } catch {
    return { ticker, label: ticker, close: null, change: null };
  }
}

export function MarketStrip() {
  const [quotes, setQuotes] = useState<Quote[]>(
    TICKERS.map((t) => ({ ...t, close: null, change: null })),
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all(TICKERS.map(({ ticker }) => fetchQuote(ticker))).then((qs) => {
      if (cancelled) return;
      setQuotes(
        qs.map((q, i) => ({ ...q, label: TICKERS[i].label })),
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section
      aria-label="Market backdrop"
      className="rounded-xl border border-border bg-card/60 p-5"
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-foreground">
          Backdrop
        </h2>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          last close · d/d
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {quotes.map((q) => {
          const pct =
            q.change != null ? (q.change * 100).toFixed(2) + "%" : "—";
          const tone =
            q.change == null
              ? "text-muted-foreground"
              : q.change > 0
                ? "text-bullish"
                : q.change < 0
                  ? "text-bearish"
                  : "text-muted-foreground";
          const sign = q.change != null && q.change > 0 ? "+" : "";
          return (
            <div key={q.ticker} className="space-y-1">
              <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                {q.ticker}
              </dt>
              <dd className="font-display text-2xl font-medium tabular-nums leading-none">
                {q.close != null ? `$${q.close.toFixed(2)}` : "—"}
              </dd>
              <dd className={`font-mono text-xs tabular-nums ${tone}`}>
                {q.change != null ? `${sign}${pct}` : ""}
              </dd>
              <dd className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                {q.label}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
