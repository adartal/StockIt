import { ShieldAlertIcon } from "lucide-react";

import { SectionMarker } from "@/components/plan/SectionMarker";
import { cn } from "@/lib/utils";
import type { RiskFlag } from "@/types/generated";

function severityStyle(s: RiskFlag["severity"]): string {
  if (s === "warn") {
    return "border-bearish/40 bg-bearish/8 text-bearish";
  }
  return "border-amber-signal/40 bg-amber-signal/10 text-amber-signal";
}

export function RiskFlags({ flags }: { flags: RiskFlag[] }) {
  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label="Risk flags" icon={ShieldAlertIcon} />
      {flags.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          No risk flags raised.
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {flags.map((f, i) => (
            <li
              key={i}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-4",
                severityStyle(f.severity),
              )}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em]">
                  {f.severity === "warn" ? "Warn" : "Info"}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {f.code}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-foreground">
                {f.message}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
