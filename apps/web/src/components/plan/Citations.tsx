import { BookOpenIcon, ExternalLinkIcon } from "lucide-react";

import { SectionMarker } from "@/components/plan/SectionMarker";
import type { Citation } from "@/types/generated";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function Citations({ sources }: { sources: Citation[] }) {
  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label={`Citations · ${sources.length}`} icon={BookOpenIcon} />
      {sources.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          No citations.
        </p>
      ) : (
        <ol className="space-y-3 border-t border-border pt-4 text-sm">
          {sources.map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-0.5 select-none font-mono text-[11px] tabular-nums text-muted-foreground">
                [{String(i + 1).padStart(2, "0")}]
              </span>
              <div className="flex-1 space-y-0.5">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-baseline gap-1.5 text-foreground hover:text-primary"
                >
                  <span className="underline decoration-border underline-offset-4 group-hover:decoration-primary">
                    {s.title}
                  </span>
                  <ExternalLinkIcon
                    className="size-3 opacity-0 group-hover:opacity-60"
                    strokeWidth={1.5}
                  />
                </a>
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  {host(s.url)} · {s.source} · {fmtDate(s.fetched_at)}
                </p>
                <p className="hidden break-all font-mono text-[10px] text-muted-foreground print:block">
                  {s.url}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
