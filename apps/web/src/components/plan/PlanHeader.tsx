import { ConvictionBar } from "@/components/plan/ConvictionBar";
import type { Plan } from "@/types/generated";

function num(s: string | null | undefined): number | null {
  if (s == null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function inferCall(plan: Plan): { label: string; tone: "bull" | "bear" | "flat" } {
  const stop = num(plan.stop.price);
  const entry = plan.entry.levels.map(num).filter((n): n is number => n != null);
  const entryAvg = entry.length ? entry.reduce((a, b) => a + b, 0) / entry.length : null;
  const long = stop != null && entryAvg != null ? entryAvg > stop : true;
  if (plan.conviction === "low") return { label: "WATCH", tone: "flat" };
  if (long) return { label: "BUY", tone: "bull" };
  return { label: "SHORT", tone: "bear" };
}

function fmtHorizon(h: Plan["horizon"]): string {
  if (h === "long_term") return "Long Term";
  if (h === "swing") return "Swing";
  return "Intraday";
}

export function PlanHeader({ plan }: { plan: Plan }) {
  const generated = new Date(plan.generated_at);
  const generatedStr = Number.isNaN(generated.getTime())
    ? plan.generated_at
    : generated.toISOString().replace("T", " · ").slice(0, 19) + " UTC";

  const call = inferCall(plan);
  const callColor =
    call.tone === "bull"
      ? "text-bullish"
      : call.tone === "bear"
        ? "text-bearish"
        : "text-muted-foreground";

  return (
    <header className="reveal-up space-y-6 border-b border-border pb-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
            {fmtHorizon(plan.horizon)} · brief
          </p>
          <h1 className="font-display text-6xl font-semibold leading-[0.95] tracking-tight sm:text-7xl">
            {plan.ticker}
          </h1>
        </div>

        <div className="flex flex-col items-start gap-3 sm:items-end">
          <div className="flex items-baseline gap-3">
            <span
              className={`font-display text-3xl font-semibold tracking-tight ${callColor}`}
            >
              {call.label}
            </span>
            <ConvictionBar conviction={plan.conviction} />
          </div>
          <dl className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            <div className="flex items-baseline gap-1.5">
              <dt>Capital</dt>
              <dd className="text-foreground normal-case tracking-normal">
                ${plan.capital}
              </dd>
            </div>
            <div className="flex items-baseline gap-1.5">
              <dt>Generated</dt>
              <dd className="text-foreground normal-case tracking-normal">
                {generatedStr}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </header>
  );
}
