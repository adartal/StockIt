"use client";

import { useEffect, useState } from "react";

const STAGES = [
  { label: "Fetching fundamentals", weight: 0.18 },
  { label: "Pulling price history", weight: 0.12 },
  { label: "Scanning news", weight: 0.14 },
  { label: "Reading macro context", weight: 0.1 },
  { label: "Drafting thesis", weight: 0.22 },
  { label: "Synthesizing risks", weight: 0.14 },
  { label: "Persisting brief", weight: 0.1 },
] as const;

const TYPICAL_MS = 90_000;

function useElapsed(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) return;
    const start = Date.now();
    const id = window.setInterval(() => {
      setElapsed(Date.now() - start);
    }, 250);
    return () => {
      window.clearInterval(id);
    };
  }, [active]);
  return active ? elapsed : 0;
}

function computeProgress(elapsedMs: number): {
  activeIndex: number;
  progressPct: number;
} {
  const totalWeight = STAGES.reduce((a, s) => a + s.weight, 0);
  const ratio = Math.min(elapsedMs / TYPICAL_MS, 0.97);
  let walked = 0;
  for (let i = 0; i < STAGES.length; i++) {
    walked += STAGES[i].weight / totalWeight;
    if (ratio <= walked) {
      return { activeIndex: i, progressPct: ratio * 100 };
    }
  }
  return { activeIndex: STAGES.length - 1, progressPct: ratio * 100 };
}

export function GenerationProgress({
  open,
  ticker,
}: {
  open: boolean;
  ticker: string;
}) {
  const elapsed = useElapsed(open);
  const { activeIndex, progressPct } = computeProgress(elapsed);
  const elapsedSec = Math.floor(elapsed / 1000);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Generating brief"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/85 backdrop-blur-md print:hidden"
    >
      <div className="reveal-up w-full max-w-lg space-y-6 rounded-xl border border-border bg-card p-8 shadow-[0_2px_40px_color-mix(in_oklch,var(--foreground)_8%,transparent)]">
        <header className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
            Briefing in progress
          </p>
          <h2 className="font-display text-3xl font-medium tracking-tight">
            {ticker.toUpperCase()}
          </h2>
        </header>

        <ol className="space-y-2 font-mono text-sm">
          {STAGES.map((s, i) => {
            const done = i < activeIndex;
            const active = i === activeIndex;
            return (
              <li
                key={s.label}
                className={`flex items-center gap-3 transition-opacity duration-300 ${
                  done || active ? "opacity-100" : "opacity-40"
                }`}
              >
                <span
                  aria-hidden
                  className={`inline-block size-2 shrink-0 rounded-full ${
                    done
                      ? "bg-primary"
                      : active
                        ? "bg-primary animate-pulse"
                        : "bg-border"
                  }`}
                />
                <span
                  className={`flex-1 ${
                    active ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {s.label}
                  {active ? <span className="ml-1 animate-pulse">_</span> : null}
                </span>
                {done ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                    done
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>

        <div className="space-y-2">
          <div className="relative h-px overflow-hidden bg-border">
            <div
              className="absolute inset-y-0 left-0 bg-primary transition-[width] duration-500 ease-linear"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="flex justify-between font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            <span>elapsed · {elapsedSec}s</span>
            <span>typical · 90s</span>
          </div>
        </div>

        <p className="text-pretty text-xs leading-relaxed text-muted-foreground">
          The desk is reading filings, prices, news, and macro context — and
          drafting a thesis you can act on. Stages are estimated; close timing
          depends on each provider.
        </p>
      </div>
    </div>
  );
}
