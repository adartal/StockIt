"use client";

import { useEffect, useState } from "react";

interface OHLCV {
  time: string;
  close: number;
}

interface PricesResponse {
  ticker: string;
  bars: OHLCV[];
}

type Tone = "bullish" | "bearish" | "neutral";

const TONE_COLORS: Record<Tone, { line: string; fillTop: string }> = {
  bullish: { line: "rgb(46,125,50)", fillTop: "rgba(46,125,50,0.18)" },
  bearish: { line: "rgb(176,52,38)", fillTop: "rgba(176,52,38,0.18)" },
  neutral: { line: "rgb(110,110,120)", fillTop: "rgba(110,110,120,0.14)" },
};

interface Paths {
  line: string;
  area: string;
  tone: Tone;
  width: number;
}

function computePaths(closes: number[], height: number): Paths | null {
  if (closes.length < 2) return null;

  const width = closes.length - 1;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const inset = 1;
  const usable = Math.max(height - inset * 2, 1);
  const range = max - min || 1;

  const points = closes.map((value, i) => {
    const x = i;
    const y = inset + (1 - (value - min) / range) * usable;
    return { x, y };
  });

  const line = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y.toFixed(3)}`)
    .join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;

  const first = closes[0];
  const last = closes[closes.length - 1];
  const tone: Tone = last > first ? "bullish" : last < first ? "bearish" : "neutral";

  return { line, area, tone, width };
}

export function Sparkline({
  ticker,
  height = 32,
  range = "3mo",
  interval = "1d",
}: {
  ticker: string;
  height?: number;
  range?: string;
  interval?: string;
}) {
  const [paths, setPaths] = useState<Paths | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(
      `/api/prices?ticker=${encodeURIComponent(ticker)}&range=${range}&interval=${interval}`,
    )
      .then((r) => (r.ok ? (r.json() as Promise<PricesResponse>) : Promise.reject()))
      .then((data) => {
        if (cancelled) return;
        const closes = data.bars.map((b) => b.close);
        setPaths(computePaths(closes, height));
      })
      .catch(() => {
        if (!cancelled) setPaths(null);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, height, range, interval]);

  if (!paths) {
    return <div className="w-full" style={{ height }} aria-hidden />;
  }

  const colors = TONE_COLORS[paths.tone];
  const gradientId = `spark-grad-${paths.tone}`;

  return (
    <svg
      className="block w-full"
      style={{ height }}
      viewBox={`0 0 ${paths.width} ${height}`}
      preserveAspectRatio="none"
      data-tone={paths.tone}
      aria-hidden
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={colors.fillTop} />
          <stop offset="100%" stopColor="rgba(0,0,0,0)" />
        </linearGradient>
      </defs>
      <path d={paths.area} fill={`url(#${gradientId})`} stroke="none" />
      <path
        d={paths.line}
        fill="none"
        stroke={colors.line}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
