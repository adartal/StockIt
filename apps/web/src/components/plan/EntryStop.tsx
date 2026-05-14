import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Plan } from "@/types/generated";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

export function EntryStop({ plan }: { plan: Plan }) {
  const { entry, sizing, stop } = plan;

  return (
    <Card className="ring-2 ring-foreground/15">
      <CardHeader>
        <CardTitle>Entry · Sizing · Stop</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-3">
        <div className="space-y-3">
          <h3 className="font-heading text-sm font-semibold">Entry</h3>
          <Row label="Kind" value={<span className="capitalize">{entry.kind.replace("_", " ")}</span>} />
          <Row
            label="Levels"
            value={entry.levels.length > 0 ? entry.levels.join(", ") : "—"}
          />
          <Row label="Conditions" value={entry.conditions || "—"} />
        </div>

        <div className="space-y-3 md:border-l md:pl-6">
          <h3 className="font-heading text-sm font-semibold">Sizing</h3>
          <Row label="Risk %" value={`${(sizing.risk_pct * 100).toFixed(2)}%`} />
          <Row label="Shares" value={sizing.shares.toLocaleString()} />
          <Row label="$ Exposure" value={`$${sizing.dollar_exposure}`} />
          <Row label="R value" value={`$${sizing.R_value}`} />
        </div>

        <div className="space-y-3 md:border-l md:pl-6">
          <h3 className="font-heading text-sm font-semibold">Stop</h3>
          <Row label="Price" value={<span className="text-base">${stop.price}</span>} />
          <Row label="Kind" value={<span className="capitalize">{stop.kind.replace("_", " ")}</span>} />
          <Separator className="my-2" />
          <p className="text-sm text-muted-foreground">{stop.rationale}</p>
        </div>
      </CardContent>
    </Card>
  );
}
