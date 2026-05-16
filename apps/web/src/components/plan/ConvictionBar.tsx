import { cn } from "@/lib/utils";
import type { Plan } from "@/types/generated";

const FILLED: Record<Plan["conviction"], number> = {
  low: 2,
  medium: 3,
  high: 5,
};

export function ConvictionBar({
  conviction,
  className,
}: {
  conviction: Plan["conviction"];
  className?: string;
}) {
  const filled = FILLED[conviction];
  return (
    <div
      className={cn("flex items-center gap-2", className)}
      role="img"
      aria-label={`Conviction ${conviction} (${filled} of 5)`}
    >
      <div className="flex gap-0.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "block h-3 w-1.5 rounded-[2px]",
              i < filled ? "bg-primary" : "bg-border",
              i < filled && i === filled - 1 && "animate-signal-pulse",
            )}
          />
        ))}
      </div>
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {conviction}
      </span>
    </div>
  );
}
