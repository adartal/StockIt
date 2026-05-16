import { notFound } from "next/navigation";

import {
  Catalysts,
  Citations,
  DecisionRail,
  EntryStop,
  ExportButtons,
  Exits,
  Notes,
  PlanHeader,
  PriceChart,
  RiskFlags,
  Thesis,
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
    <main className="mx-auto w-full max-w-6xl p-6">
      <div className="mb-6 flex items-center justify-between gap-4 print:hidden">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Brief #{id.slice(0, 8)}
        </p>
        <ExportButtons plan={plan} />
      </div>

      <article id="plan-print-root" className="grid gap-10 lg:grid-cols-[1fr_280px]">
        <div className="space-y-12">
          <PlanHeader plan={plan} />
          <EntryStop plan={plan} />
          <Thesis thesis={plan.thesis} />
          <PriceChart ticker={plan.ticker} horizon={plan.horizon} plan={plan} />
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
        </div>

        <DecisionRail plan={plan} />
      </article>
    </main>
  );
}
