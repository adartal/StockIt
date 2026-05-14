import { notFound } from "next/navigation";

import {
  Catalysts,
  Citations,
  EntryStop,
  ExportButtons,
  Notes,
  PlanHeader,
  PriceChart,
  RiskFlags,
  Thesis,
  Exits,
} from "@/components/plan";
import { getPlan, listNotes } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PlanPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const plan = await getPlan(id);
  if (!plan) notFound();

  const notes = await listNotes(id).catch(() => []);

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-4 print:hidden">
        <p className="text-sm text-muted-foreground">Plan #{id.slice(0, 8)}</p>
        <ExportButtons plan={plan} />
      </div>

      <article id="plan-print-root" className="space-y-6">
        <PlanHeader plan={plan} />
        <EntryStop plan={plan} />
        <Thesis thesis={plan.thesis} />
        <PriceChart ticker={plan.ticker} horizon={plan.horizon} />
        <Exits exits={plan.exits} />
        <Catalysts catalysts={plan.catalysts} />
        <RiskFlags flags={plan.risk_flags} />
        <Citations sources={plan.sources} />
        <Notes
          planId={id}
          initialNotes={notes.map((n) => ({
            id: n.id,
            body: n.body,
            created_at: n.created_at,
          }))}
        />
      </article>
    </main>
  );
}
