import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { Plan } from "@/types/generated";

function convictionVariant(c: Plan["conviction"]) {
  switch (c) {
    case "high":
      return "default" as const;
    case "medium":
      return "secondary" as const;
    case "low":
      return "outline" as const;
  }
}

export function PlanHeader({ plan }: { plan: Plan }) {
  const generated = new Date(plan.generated_at);
  const generatedStr = Number.isNaN(generated.getTime())
    ? plan.generated_at
    : generated.toISOString().replace("T", " ").slice(0, 16) + " UTC";

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-baseline gap-3">
          <h1 className="font-heading text-3xl font-semibold tracking-tight">
            {plan.ticker}
          </h1>
          <span className="text-sm text-muted-foreground capitalize">
            {plan.horizon.replace("_", " ")}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="flex items-center gap-1">
            <span className="text-muted-foreground">Conviction:</span>
            <Badge variant={convictionVariant(plan.conviction)} className="capitalize">
              {plan.conviction}
            </Badge>
          </span>
          <span>
            <span className="text-muted-foreground">Capital:</span>{" "}
            <span className="font-medium">${plan.capital}</span>
          </span>
          <span className="text-muted-foreground">{generatedStr}</span>
        </div>
      </CardContent>
    </Card>
  );
}
