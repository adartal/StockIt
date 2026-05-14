import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { RiskFlag } from "@/types/generated";

function severityVariant(s: RiskFlag["severity"]) {
  return s === "warn" ? ("destructive" as const) : ("secondary" as const);
}

export function RiskFlags({ flags }: { flags: RiskFlag[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Risk flags</CardTitle>
      </CardHeader>
      <CardContent>
        {flags.length === 0 ? (
          <p className="text-sm text-muted-foreground">No risk flags raised.</p>
        ) : (
          <ul className="space-y-2">
            {flags.map((f, i) => (
              <li key={i} className="flex items-start gap-3">
                <Badge variant={severityVariant(f.severity)} className="uppercase">
                  {f.severity}
                </Badge>
                <div className="flex flex-col">
                  <span className="font-mono text-xs text-muted-foreground">
                    {f.code}
                  </span>
                  <span className="text-sm">{f.message}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
