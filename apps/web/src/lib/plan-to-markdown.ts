import type { Plan } from "@/types/generated";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function table(headers: string[], rows: string[][]): string {
  if (rows.length === 0) return "_(none)_";
  const head = `| ${headers.join(" | ")} |`;
  const sep = `| ${headers.map(() => "---").join(" | ")} |`;
  const body = rows.map((r) => `| ${r.join(" | ")} |`).join("\n");
  return `${head}\n${sep}\n${body}`;
}

export function planToMarkdown(plan: Plan): string {
  const lines: string[] = [];

  lines.push(`# ${plan.ticker} — ${plan.horizon} plan`);
  lines.push("");
  lines.push(
    `**Conviction:** ${plan.conviction}  |  **Capital:** $${plan.capital}  |  **Generated:** ${fmtDate(plan.generated_at)}`,
  );
  lines.push("");

  lines.push("## Thesis");
  lines.push("");
  lines.push(plan.thesis.trim() || "_(no thesis)_");
  lines.push("");

  lines.push("## Entry");
  lines.push("");
  lines.push(`- **Kind:** ${plan.entry.kind}`);
  if (plan.entry.levels.length > 0) {
    lines.push(`- **Levels:** ${plan.entry.levels.join(", ")}`);
  }
  if (plan.entry.conditions) {
    lines.push(`- **Conditions:** ${plan.entry.conditions}`);
  }
  lines.push("");

  lines.push("## Sizing");
  lines.push("");
  lines.push(`- **Risk %:** ${(plan.sizing.risk_pct * 100).toFixed(2)}%`);
  lines.push(`- **Shares:** ${plan.sizing.shares}`);
  lines.push(`- **$ Exposure:** $${plan.sizing.dollar_exposure}`);
  lines.push(`- **R value:** $${plan.sizing.R_value}`);
  lines.push("");

  lines.push("## Stop");
  lines.push("");
  lines.push(`- **Price:** $${plan.stop.price}`);
  lines.push(`- **Kind:** ${plan.stop.kind}`);
  lines.push(`- **Rationale:** ${plan.stop.rationale}`);
  lines.push("");

  lines.push("## Exits");
  lines.push("");
  lines.push(
    table(
      ["Kind", "Price", "Portion", "Trigger"],
      plan.exits.map((e) => [
        e.kind,
        e.price ?? "—",
        e.portion != null ? `${(e.portion * 100).toFixed(0)}%` : "—",
        e.trigger,
      ]),
    ),
  );
  lines.push("");

  lines.push("## Catalysts");
  lines.push("");
  lines.push(
    table(
      ["Date", "Kind", "Description"],
      plan.catalysts.map((c) => [c.date, c.kind, c.description]),
    ),
  );
  lines.push("");

  lines.push("## Risk flags");
  lines.push("");
  if (plan.risk_flags.length === 0) {
    lines.push("_(none)_");
  } else {
    for (const f of plan.risk_flags) {
      lines.push(`- **[${f.severity.toUpperCase()}] ${f.code}** — ${f.message}`);
    }
  }
  lines.push("");

  lines.push(`## Review cadence`);
  lines.push("");
  lines.push(plan.review_cadence || "_(unspecified)_");
  lines.push("");

  lines.push("## Citations");
  lines.push("");
  if (plan.sources.length === 0) {
    lines.push("_(none)_");
  } else {
    for (const s of plan.sources) {
      lines.push(`- [${s.title}](${s.url}) — ${s.source} (${fmtDate(s.fetched_at)})`);
    }
  }
  lines.push("");

  return lines.join("\n");
}
