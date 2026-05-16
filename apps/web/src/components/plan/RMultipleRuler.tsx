import { cn } from "@/lib/utils";
import type { Plan } from "@/types/generated";

function num(s: string | null | undefined): number | null {
  if (s == null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function bestTarget(plan: Plan): number | null {
  const scaleOuts = plan.exits
    .filter((e) => e.kind === "scale_out")
    .map((e) => num(e.price))
    .filter((n): n is number => n != null);
  if (scaleOuts.length === 0) return null;
  return Math.max(...scaleOuts);
}

function bestEntry(plan: Plan): number | null {
  const levels = plan.entry.levels.map(num).filter((n): n is number => n != null);
  if (levels.length === 0) return null;
  return levels.reduce((a, b) => a + b, 0) / levels.length;
}

function fmtPrice(n: number): string {
  return `$${n.toFixed(2)}`;
}

export function RMultipleRuler({ plan }: { plan: Plan }) {
  const stop = num(plan.stop.price);
  const entry = bestEntry(plan);
  const target = bestTarget(plan);

  if (stop == null || entry == null) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/30 p-4 text-center text-xs text-muted-foreground">
        Ruler unavailable — stop or entry not numeric.
      </div>
    );
  }

  const risk = Math.abs(entry - stop);
  if (risk === 0) return null;

  const long = entry > stop;
  const rMultiple = target != null ? (target - entry) / (entry - stop) : null;

  const lo = long ? stop : target ?? entry;
  const hi = long ? target ?? entry : stop;
  const span = Math.max(hi - lo, risk * 1.2);
  const padded = span * 0.06;
  const min = lo - padded;
  const max = hi + padded;
  const pos = (v: number) => ((v - min) / (max - min)) * 100;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        <span>Risk · Reward</span>
        <span className="font-mono normal-case tracking-normal text-foreground">
          {rMultiple != null
            ? `${rMultiple.toFixed(2)}R reward / 1R risk`
            : `target not set`}
        </span>
      </div>

      <div className="relative h-9">
        {/* Track */}
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />

        {/* Risk segment (stop → entry) */}
        <div
          className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-bearish/70"
          style={{
            left: `${pos(Math.min(stop, entry))}%`,
            width: `${Math.abs(pos(entry) - pos(stop))}%`,
          }}
        />

        {/* Reward segment (entry → target) */}
        {target != null ? (
          <div
            className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-bullish/70"
            style={{
              left: `${pos(Math.min(entry, target))}%`,
              width: `${Math.abs(pos(target) - pos(entry))}%`,
            }}
          />
        ) : null}

        {/* Tick: stop */}
        <Tick label="STOP" sub={fmtPrice(stop)} x={pos(stop)} tone="bearish" />
        {/* Tick: entry */}
        <Tick label="ENTRY" sub={fmtPrice(entry)} x={pos(entry)} tone="ink" />
        {/* Tick: target */}
        {target != null ? (
          <Tick label="TARGET" sub={fmtPrice(target)} x={pos(target)} tone="bullish" />
        ) : null}
      </div>
    </div>
  );
}

function Tick({
  label,
  sub,
  x,
  tone,
}: {
  label: string;
  sub: string;
  x: number;
  tone: "bullish" | "bearish" | "ink";
}) {
  const dot =
    tone === "bullish"
      ? "bg-bullish"
      : tone === "bearish"
        ? "bg-bearish"
        : "bg-foreground";
  return (
    <div
      className="absolute top-0 flex h-9 -translate-x-1/2 flex-col items-center"
      style={{ left: `${x}%` }}
    >
      <span
        className={cn(
          "mt-3.5 block h-2 w-2 rounded-full ring-2 ring-background",
          dot,
        )}
      />
      <div className="absolute -top-0.5 flex flex-col items-center whitespace-nowrap text-[10px] leading-tight">
        <span className="font-mono uppercase tracking-[0.15em] text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="absolute top-6 whitespace-nowrap font-mono text-[11px] tabular-nums">
        {sub}
      </div>
    </div>
  );
}
