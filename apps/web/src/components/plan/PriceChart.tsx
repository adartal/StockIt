"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  LineSeries,
  type IChartApi,
  type Time,
} from "lightweight-charts";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface OHLCV {
  time: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface PricesResponse {
  ticker: string;
  bars: OHLCV[];
}

function sma(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    if (i >= window - 1) out[i] = sum / window;
  }
  return out;
}

export function PriceChart({ ticker, horizon }: { ticker: string; horizon: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [status, setStatus] = useState<
    { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string }
  >({ kind: "loading" });
  const error = status.kind === "error" ? status.message : null;
  const loading = status.kind === "loading";

  useEffect(() => {
    let cancelled = false;

    const range = horizon === "intraday" ? "5d" : horizon === "swing" ? "6mo" : "2y";
    const interval = horizon === "intraday" ? "15m" : "1d";

    fetch(`/api/prices?ticker=${encodeURIComponent(ticker)}&range=${range}&interval=${interval}`)
      .then((r) => {
        if (!r.ok) throw new Error(`prices ${r.status}`);
        return r.json() as Promise<PricesResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        if (!containerRef.current) return;
        const chart = createChart(containerRef.current, {
          height: 360,
          layout: {
            background: { color: "transparent" },
            textColor: "#888",
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: "rgba(0,0,0,0.05)" },
            horzLines: { color: "rgba(0,0,0,0.05)" },
          },
          timeScale: { borderColor: "rgba(0,0,0,0.1)" },
          rightPriceScale: { borderColor: "rgba(0,0,0,0.1)" },
        });
        chartRef.current = chart;

        const candle = chart.addSeries(CandlestickSeries, {
          upColor: "#16a34a",
          downColor: "#dc2626",
          wickUpColor: "#16a34a",
          wickDownColor: "#dc2626",
          borderVisible: false,
        });
        candle.setData(
          data.bars.map((b) => ({
            time: b.time as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          })),
        );

        const closes = data.bars.map((b) => b.close);
        if (closes.length >= 20) {
          const sma20Line = chart.addSeries(LineSeries, {
            color: "#2563eb",
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          sma20Line.setData(
            sma(closes, 20)
              .map((v, i) => (v == null ? null : { time: data.bars[i].time as Time, value: v }))
              .filter((p): p is { time: Time; value: number } => p !== null),
          );
        }
        if (closes.length >= 50) {
          const sma50Line = chart.addSeries(LineSeries, {
            color: "#f59e0b",
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          sma50Line.setData(
            sma(closes, 50)
              .map((v, i) => (v == null ? null : { time: data.bars[i].time as Time, value: v }))
              .filter((p): p is { time: Time; value: number } => p !== null),
          );
        }

        chart.timeScale().fitContent();

        const ro = new ResizeObserver(() => {
          if (containerRef.current) {
            chart.applyOptions({ width: containerRef.current.clientWidth });
          }
        });
        ro.observe(containerRef.current);

        setStatus({ kind: "ready" });
        return () => {
          ro.disconnect();
          chart.remove();
          chartRef.current = null;
        };
      })
      .catch((e) => {
        if (cancelled) return;
        setStatus({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });

    return () => {
      cancelled = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [ticker, horizon]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Price — {ticker} <span className="text-xs font-normal text-muted-foreground">(SMA 20 · 50)</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-sm text-destructive">Could not load prices: {error}</p>
        )}
        {loading && !error && (
          <p className="text-sm text-muted-foreground">Loading chart…</p>
        )}
        <div ref={containerRef} className="w-full print:hidden" />
        <p className="hidden text-xs text-muted-foreground print:block">
          Chart hidden in print view — see live page.
        </p>
      </CardContent>
    </Card>
  );
}
