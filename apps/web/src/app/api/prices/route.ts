import { NextRequest, NextResponse } from "next/server";

import { auth } from "../../../../auth";

interface YahooChartResponse {
  chart: {
    result?: Array<{
      meta: { symbol: string };
      timestamp?: number[];
      indicators: {
        quote?: Array<{
          open?: (number | null)[];
          high?: (number | null)[];
          low?: (number | null)[];
          close?: (number | null)[];
          volume?: (number | null)[];
        }>;
      };
    }>;
    error?: { code: string; description: string } | null;
  };
}

function toDate(ts: number, daily: boolean): string {
  const d = new Date(ts * 1000);
  return daily
    ? d.toISOString().slice(0, 10)
    : d.toISOString().replace("T", " ").slice(0, 16);
}

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(req.url);
  const ticker = url.searchParams.get("ticker")?.toUpperCase().trim();
  const range = url.searchParams.get("range") ?? "6mo";
  const interval = url.searchParams.get("interval") ?? "1d";

  if (!ticker || !/^[A-Z][A-Z0-9.\-]{0,15}$/.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }

  const yahooUrl =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}` +
    `?range=${encodeURIComponent(range)}&interval=${encodeURIComponent(interval)}`;

  const upstream = await fetch(yahooUrl, {
    headers: { "User-Agent": "Mozilla/5.0 StockIt/1.0" },
    cache: "no-store",
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `upstream ${upstream.status}` },
      { status: 502 },
    );
  }

  const data = (await upstream.json()) as YahooChartResponse;
  const result = data.chart.result?.[0];
  if (!result || !result.timestamp) {
    return NextResponse.json({ ticker, bars: [] });
  }

  const daily = interval.endsWith("d") || interval.endsWith("wk") || interval.endsWith("mo");
  const q = result.indicators.quote?.[0] ?? {};
  const bars = result.timestamp
    .map((ts, i) => {
      const open = q.open?.[i];
      const high = q.high?.[i];
      const low = q.low?.[i];
      const close = q.close?.[i];
      const volume = q.volume?.[i];
      if (open == null || high == null || low == null || close == null) return null;
      return {
        time: toDate(ts, daily),
        open,
        high,
        low,
        close,
        volume: volume ?? 0,
      };
    })
    .filter((b): b is NonNullable<typeof b> => b !== null);

  return NextResponse.json({ ticker, bars });
}
