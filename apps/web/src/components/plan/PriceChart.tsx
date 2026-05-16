"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { CandlestickChartIcon } from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";

import { SectionMarker } from "@/components/plan/SectionMarker";
import type { Plan } from "@/types/generated";

interface OHLCV {
  time: string;
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

function num(s: string | null | undefined): number | null {
  if (s == null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function PriceChart({
  ticker,
  horizon,
  plan,
}: {
  ticker: string;
  horizon: string;
  plan?: Plan;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const { resolvedTheme } = useTheme();
  const [status, setStatus] = useState<
    { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string }
  >({ kind: "loading" });
  const error = status.kind === "error" ? status.message : null;
  const loading = status.kind === "loading";

  useEffect(() => {
    let cancelled = false;

    const range = horizon === "intraday" ? "5d" : horizon === "swing" ? "6mo" : "2y";
    const interval = horizon === "intraday" ? "15m" : "1d";

    const isDark = resolvedTheme === "dark";
    const palette = isDark
      ? {
          up: "rgb(123,196,135)",
          down: "rgb(213,114,103)",
          sma20: "rgb(232,180,90)", // amber
          sma50: "rgb(160,180,210)", // steel
          textColor: "rgba(220,220,220,0.55)",
          grid: "rgba(255,255,255,0.04)",
        }
      : {
          up: "rgb(50,120,72)",
          down: "rgb(176,52,38)",
          sma20: "rgb(141,40,30)", // oxblood
          sma50: "rgb(184,134,28)", // antique gold
          textColor: "rgba(40,40,40,0.55)",
          grid: "rgba(0,0,0,0.04)",
        };

    fetch(`/api/prices?ticker=${encodeURIComponent(ticker)}&range=${range}&interval=${interval}`)
      .then((r) => {
        if (!r.ok) throw new Error(`prices ${r.status}`);
        return r.json() as Promise<PricesResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        if (!containerRef.current) return;
        const chart = createChart(containerRef.current, {
          height: 380,
          layout: {
            background: { color: "transparent" },
            textColor: palette.textColor,
            attributionLogo: false,
            fontFamily: 'ui-sans-serif, system-ui',
          },
          grid: {
            vertLines: { color: palette.grid },
            horzLines: { color: palette.grid },
          },
          timeScale: { borderColor: palette.grid },
          rightPriceScale: { borderColor: palette.grid },
        });
        chartRef.current = chart;

        const candle = chart.addSeries(CandlestickSeries, {
          upColor: palette.up,
          downColor: palette.down,
          wickUpColor: palette.up,
          wickDownColor: palette.down,
          borderVisible: false,
        });
        candleRef.current = candle;
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
            color: palette.sma20,
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
            color: palette.sma50,
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

        // Price-lines for entry / stop / target — the "what to do" overlay.
        if (plan) {
          const stop = num(plan.stop.price);
          const entries = plan.entry.levels.map(num).filter((n): n is number => n != null);
          const targets = plan.exits
            .filter((e) => e.kind === "scale_out")
            .map((e) => num(e.price))
            .filter((n): n is number => n != null);

          if (stop != null) {
            candle.createPriceLine({
              price: stop,
              color: palette.down,
              lineWidth: 1,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: "STOP",
            });
          }
          for (const e of entries) {
            candle.createPriceLine({
              price: e,
              color: palette.sma20,
              lineWidth: 1,
              lineStyle: 0,
              axisLabelVisible: true,
              title: "ENTRY",
            });
          }
          for (const t of targets) {
            candle.createPriceLine({
              price: t,
              color: palette.up,
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: "TGT",
            });
          }
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
  }, [ticker, horizon, plan, resolvedTheme]);

  return (
    <section className="reveal-up space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionMarker label={`Price · ${ticker}`} icon={CandlestickChartIcon} />
        <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          <Legend dot="bg-primary" label="SMA 20" />
          <Legend dot="bg-chart-5" label="SMA 50" />
          {plan ? <Legend dot="bg-bullish" label="Target" /> : null}
          {plan ? <Legend dot="bg-bearish" label="Stop" /> : null}
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-3">
        {error && (
          <p className="px-3 py-6 text-sm text-destructive">Could not load prices: {error}</p>
        )}
        {loading && !error && (
          <p className="px-3 py-6 text-sm text-muted-foreground">Loading chart…</p>
        )}
        <div ref={containerRef} className="w-full print:hidden" />
        <p className="hidden text-xs text-muted-foreground print:block">
          Chart hidden in print view — see live page.
        </p>
      </div>
    </section>
  );
}

function Legend({ dot, label }: { dot: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`block h-2 w-2 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
