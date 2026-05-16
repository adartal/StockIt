import { DoorOpenIcon } from "lucide-react";

import { SectionMarker } from "@/components/plan/SectionMarker";
import type { ExitLevel } from "@/types/generated";

const KIND_LABEL: Record<ExitLevel["kind"], string> = {
  scale_out: "Scale out",
  time_stop: "Time stop",
  invalidation: "Invalidation",
};

export function Exits({ exits }: { exits: ExitLevel[] }) {
  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label="Exit plan" icon={DoorOpenIcon} />
      {exits.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          No exits defined.
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {exits.map((e, i) => (
            <li
              key={i}
              className="group relative flex flex-col gap-2 rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                  {KIND_LABEL[e.kind] ?? e.kind}
                </span>
                {e.portion != null ? (
                  <span className="font-mono text-[11px] tabular-nums text-primary">
                    {(e.portion * 100).toFixed(0)}%
                  </span>
                ) : null}
              </div>
              <p className="font-display text-2xl font-medium tabular-nums">
                {e.price ? `$${e.price}` : "—"}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {e.trigger}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
