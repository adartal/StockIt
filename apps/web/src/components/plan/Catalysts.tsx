import {
  BriefcaseIcon,
  CalendarClockIcon,
  GlobeIcon,
  LandmarkIcon,
  TrendingUpIcon,
} from "lucide-react";

import { SectionMarker } from "@/components/plan/SectionMarker";
import type { Catalyst } from "@/types/generated";

const KIND_GLYPH = {
  earnings: TrendingUpIcon,
  macro: GlobeIcon,
  corporate: BriefcaseIcon,
  other: LandmarkIcon,
} as const;

function fmtDate(iso: string): { date: string; weekday: string } {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: iso, weekday: "" };
  return {
    date: d.toLocaleDateString(undefined, {
      month: "short",
      day: "2-digit",
      year: "numeric",
    }),
    weekday: d.toLocaleDateString(undefined, { weekday: "short" }),
  };
}

export function Catalysts({ catalysts }: { catalysts: Catalyst[] }) {
  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label="Catalysts" icon={CalendarClockIcon} />
      {catalysts.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No catalysts identified.
        </p>
      ) : (
        <ol className="relative space-y-6 border-l border-border pl-6">
          {catalysts.map((c, i) => {
            const Glyph = KIND_GLYPH[c.kind] ?? LandmarkIcon;
            const { date, weekday } = fmtDate(c.date);
            return (
              <li key={i} className="relative">
                <span className="absolute -left-[33px] top-0 flex size-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
                  <Glyph className="size-3" strokeWidth={1.5} />
                </span>
                <div className="space-y-1">
                  <div className="flex items-baseline gap-3">
                    <span className="font-mono text-xs tabular-nums text-foreground">
                      {date}
                    </span>
                    {weekday ? (
                      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                        {weekday}
                      </span>
                    ) : null}
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
                      {c.kind}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed text-foreground">
                    {c.description}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
