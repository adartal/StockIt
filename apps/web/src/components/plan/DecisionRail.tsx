import { ConvictionBar } from "@/components/plan/ConvictionBar";
import type { Plan } from "@/types/generated";

function num(s: string | null | undefined): number | null {
  if (s == null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function fmtPrice(n: number): string {
  return `$${n.toFixed(2)}`;
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "bull" | "bear" | "ink";
}) {
  const color =
    tone === "bull"
      ? "text-bullish"
      : tone === "bear"
        ? "text-bearish"
        : "text-foreground";
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-2 last:border-b-0">
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </span>
      <span className={`font-mono text-sm tabular-nums ${color}`}>{value}</span>
    </div>
  );
}

export function DecisionRail({ plan }: { plan: Plan }) {
  const stop = num(plan.stop.price);
  const entries = plan.entry.levels.map(num).filter((n): n is number => n != null);
  const entryAvg = entries.length ? entries.reduce((a, b) => a + b, 0) / entries.length : null;
  const targets = plan.exits
    .filter((e) => e.kind === "scale_out")
    .map((e) => num(e.price))
    .filter((n): n is number => n != null);
  const target = targets.length ? Math.max(...targets) : null;

  const rMultiple =
    target != null && entryAvg != null && stop != null
      ? (target - entryAvg) / (entryAvg - stop)
      : null;

  const riskFlags = plan.risk_flags;
  const warnCount = riskFlags.filter((r) => r.severity === "warn").length;

  return (
    <aside
      className="space-y-5 rounded-xl border border-border bg-card/80 p-5 backdrop-blur-sm lg:sticky lg:top-20 print:hidden"
      aria-label="Decision rail"
    >
      <div className="space-y-3 border-b border-border pb-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          Decision rail
        </p>
        <div className="flex items-baseline justify-between">
          <span className="font-display text-4xl font-semibold tracking-tight">
            {plan.ticker}
          </span>
          <ConvictionBar conviction={plan.conviction} />
        </div>
      </div>

      <div>
        <Stat
          label="Entry"
          value={entryAvg != null ? fmtPrice(entryAvg) : "—"}
        />
        <Stat
          label="Stop"
          tone="bear"
          value={stop != null ? fmtPrice(stop) : "—"}
        />
        <Stat
          label="Target"
          tone="bull"
          value={target != null ? fmtPrice(target) : "—"}
        />
        <Stat
          label="R:R"
          value={rMultiple != null ? `${rMultiple.toFixed(2)}×` : "—"}
        />
      </div>

      <div className="border-t border-border pt-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          Sizing
        </p>
        <div className="mt-2 space-y-1 text-sm">
          <div className="flex items-baseline justify-between">
            <span className="text-muted-foreground">Shares</span>
            <span className="font-mono tabular-nums">
              {plan.sizing.shares.toLocaleString()}
            </span>
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-muted-foreground">Risk %</span>
            <span className="font-mono tabular-nums">
              {(plan.sizing.risk_pct * 100).toFixed(2)}%
            </span>
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-muted-foreground">$ exposure</span>
            <span className="font-mono tabular-nums">
              ${plan.sizing.dollar_exposure}
            </span>
          </div>
        </div>
      </div>

      <div className="border-t border-border pt-4">
        <div className="flex items-baseline justify-between">
          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
            Risk
          </p>
          <span className="font-mono text-[11px] text-foreground">
            {riskFlags.length} flags · {warnCount} warn
          </span>
        </div>
        <ul className="mt-2 flex flex-wrap gap-1">
          {riskFlags.map((f, i) => (
            <li
              key={i}
              title={f.message}
              className={`font-mono text-[10px] tabular-nums ${
                f.severity === "warn"
                  ? "text-bearish"
                  : "text-amber-signal"
              }`}
            >
              {f.code}
            </li>
          ))}
          {riskFlags.length === 0 ? (
            <li className="text-xs text-muted-foreground">—</li>
          ) : null}
        </ul>
      </div>

      <div className="border-t border-border pt-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          Review
        </p>
        <p className="mt-1 text-xs leading-relaxed text-foreground">
          {plan.review_cadence}
        </p>
      </div>
    </aside>
  );
}
