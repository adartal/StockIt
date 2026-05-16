"use client";

import { useState, useTransition } from "react";
import { CheckCircle2Icon, SparklesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import type { UserRiskConfig } from "@/lib/api";
import { updateSettings } from "./actions";

const LLMS: {
  value: UserRiskConfig["preferred_llm"];
  label: string;
  tagline: string;
}[] = [
  { value: "claude", label: "Claude", tagline: "Long-form synthesis, nuance" },
  { value: "openai", label: "OpenAI", tagline: "Broad coverage, fast" },
  { value: "gemini", label: "Gemini", tagline: "Live search, sources" },
];

function SectionHeader({
  number,
  label,
  description,
}: {
  number: string;
  label: string;
  description: string;
}) {
  return (
    <div className="space-y-1 border-b border-border pb-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
        {number} · {label}
      </p>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

export function SettingsForm({ initial }: { initial: UserRiskConfig }) {
  const [config, setConfig] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, startTransition] = useTransition();
  const [risk, setRisk] = useState(initial.risk_per_trade_pct);
  const [maxPos, setMaxPos] = useState(initial.max_position_pct);
  const [llm, setLlm] = useState<UserRiskConfig["preferred_llm"]>(
    initial.preferred_llm,
  );

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setError(null);
    setSaved(false);
    startTransition(async () => {
      const res = await updateSettings(fd);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setConfig(res.data);
      setSaved(true);
    });
  }

  // Preview based on $10,000 capital (illustrative).
  const sampleCapital = 10000;
  const sampleRiskDollars = (sampleCapital * (risk / 100)).toFixed(0);
  const sampleMaxPosDollars = (sampleCapital * (maxPos / 100)).toFixed(0);

  return (
    <form onSubmit={onSubmit} className="space-y-12">
      <section className="space-y-5">
        <SectionHeader
          number="01"
          label="Risk envelope"
          description="The desk applies these limits when sizing every plan."
        />
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="space-y-2">
            <Label
              htmlFor="risk_per_trade_pct"
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
            >
              Risk per trade · %
            </Label>
            <Input
              id="risk_per_trade_pct"
              name="risk_per_trade_pct"
              type="number"
              step="0.1"
              min="0.1"
              max="100"
              required
              value={risk}
              onChange={(e) => setRisk(parseFloat(e.target.value) || 0)}
              className="h-auto rounded-none border-0 border-b border-input bg-transparent px-0 font-display text-3xl tracking-tight focus-visible:border-primary focus-visible:ring-0"
            />
            <p className="text-xs text-muted-foreground">
              R — the dollar amount you stand to lose if the stop trips.
            </p>
          </div>
          <div className="space-y-2">
            <Label
              htmlFor="max_position_pct"
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
            >
              Max position · %
            </Label>
            <Input
              id="max_position_pct"
              name="max_position_pct"
              type="number"
              step="0.5"
              min="0.5"
              max="100"
              required
              value={maxPos}
              onChange={(e) => setMaxPos(parseFloat(e.target.value) || 0)}
              className="h-auto rounded-none border-0 border-b border-input bg-transparent px-0 font-display text-3xl tracking-tight focus-visible:border-primary focus-visible:ring-0"
            />
            <p className="text-xs text-muted-foreground">
              Ceiling on a single position as a fraction of capital.
            </p>
          </div>
        </div>
        <p className="rounded-md border border-dashed border-border bg-muted/30 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
          On <span className="font-mono text-foreground">${sampleCapital.toLocaleString()}</span> of
          capital, that means at most{" "}
          <span className="font-mono text-foreground">${sampleRiskDollars}</span> risked per trade
          and up to{" "}
          <span className="font-mono text-foreground">${sampleMaxPosDollars}</span> in any single
          position.
        </p>
      </section>

      <section className="space-y-5">
        <SectionHeader
          number="02"
          label="Model preference"
          description="Which model drafts the thesis. Each provider has different strengths."
        />
        <input type="hidden" name="preferred_llm" value={llm} />
        <RadioGroup
          value={llm}
          onValueChange={(v) => setLlm(v as UserRiskConfig["preferred_llm"])}
          className="grid gap-3 sm:grid-cols-3"
        >
          {LLMS.map((m) => (
            <Label
              key={m.value}
              htmlFor={`llm-${m.value}`}
              className={cn(
                "flex cursor-pointer flex-col gap-2 rounded-lg border bg-card p-4 transition-colors",
                "hover:border-primary/40",
                llm === m.value
                  ? "border-primary bg-primary/5"
                  : "border-input",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 font-display text-lg font-medium tracking-tight">
                  <SparklesIcon className="size-3.5 text-primary" strokeWidth={1.5} />
                  {m.label}
                </span>
                <RadioGroupItem id={`llm-${m.value}`} value={m.value} />
              </div>
              <span className="text-xs text-muted-foreground">{m.tagline}</span>
            </Label>
          ))}
        </RadioGroup>
      </section>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}
      {saved ? (
        <div className="flex items-center gap-2 rounded-md border border-bullish/40 bg-bullish/10 p-3 text-sm text-bullish">
          <CheckCircle2Icon className="size-4" strokeWidth={1.5} />
          Saved. The next plan will use the new values.
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            risk {config.risk_per_trade_pct}% · max {config.max_position_pct}% ·{" "}
            {config.preferred_llm}
          </span>
        </div>
      ) : null}

      <div className="border-t border-border pt-6">
        <Button type="submit" size="lg" disabled={pending}>
          {pending ? "Saving…" : "Save trading rules"}
        </Button>
      </div>
    </form>
  );
}
