import { CrosshairIcon, OctagonAlertIcon, ScaleIcon } from "lucide-react";

import { RMultipleRuler } from "@/components/plan/RMultipleRuler";
import { SectionMarker } from "@/components/plan/SectionMarker";
import type { Plan } from "@/types/generated";

function Stat({
  label,
  value,
  sub,
  align = "left",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <div className={align === "right" ? "text-right" : ""}>
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className="font-display text-3xl font-medium tabular-nums leading-tight">
        {value}
      </p>
      {sub ? (
        <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
      ) : null}
    </div>
  );
}

export function EntryStop({ plan }: { plan: Plan }) {
  const { entry, sizing, stop } = plan;
  const levels = entry.levels.length ? entry.levels.join(" · ") : "—";
  const riskPctStr = `${(sizing.risk_pct * 100).toFixed(2)}%`;

  return (
    <section className="reveal-up space-y-6 rounded-xl border border-border bg-card p-6 shadow-[0_1px_0_color-mix(in_oklch,var(--foreground)_5%,transparent)]">
      <SectionMarker label="The decision" icon={CrosshairIcon} />

      <RMultipleRuler plan={plan} />

      <div className="grid gap-6 sm:grid-cols-3">
        <div className="space-y-3 sm:border-r sm:border-border sm:pr-6">
          <Stat
            label="Entry"
            value={`$${levels.split(" · ")[0] ?? "—"}`}
            sub={
              <>
                <span className="capitalize">{entry.kind.replace("_", " ")}</span>
                {entry.levels.length > 1 ? (
                  <span> · ladder {levels}</span>
                ) : null}
              </>
            }
          />
          {entry.conditions ? (
            <p className="border-l-2 border-primary/60 pl-3 text-xs leading-relaxed text-muted-foreground">
              {entry.conditions}
            </p>
          ) : null}
        </div>

        <div className="space-y-3 sm:border-r sm:border-border sm:pr-6">
          <Stat
            label="Sizing"
            value={`${sizing.shares.toLocaleString()}`}
            sub={`shares · ${riskPctStr} of capital`}
          />
          <dl className="space-y-1 text-xs">
            <div className="flex items-baseline justify-between">
              <dt className="text-muted-foreground">$ exposure</dt>
              <dd className="font-mono tabular-nums">${sizing.dollar_exposure}</dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="text-muted-foreground">R value</dt>
              <dd className="font-mono tabular-nums">${sizing.R_value}</dd>
            </div>
          </dl>
          <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            <ScaleIcon className="size-3" strokeWidth={1.5} />
            position size
          </p>
        </div>

        <div className="space-y-3">
          <Stat
            label="Stop"
            value={<span className="text-bearish">${stop.price}</span>}
            sub={<span className="capitalize">{stop.kind.replace("_", " ")}</span>}
          />
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <OctagonAlertIcon className="mt-0.5 size-3.5 shrink-0 text-bearish" strokeWidth={1.5} />
            <span className="leading-relaxed">{stop.rationale}</span>
          </p>
        </div>
      </div>
    </section>
  );
}
