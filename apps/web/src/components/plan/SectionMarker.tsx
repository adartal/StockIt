import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export function SectionMarker({
  label,
  icon: Icon,
  rule = true,
  className,
}: {
  label: string;
  icon?: LucideIcon;
  rule?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      {Icon ? (
        <span className="flex size-7 items-center justify-center rounded-full border border-border bg-card text-muted-foreground">
          <Icon className="size-3.5" strokeWidth={1.5} />
        </span>
      ) : null}
      <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.22em] text-foreground">
        {label}
      </h2>
      {rule ? (
        <span className="hairline ml-2 h-px flex-1 self-center" />
      ) : null}
    </div>
  );
}
