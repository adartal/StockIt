"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import type { UserRiskConfig } from "@/lib/api";
import { updateSettings } from "./actions";

export function SettingsForm({ initial }: { initial: UserRiskConfig }) {
  const [config, setConfig] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, startTransition] = useTransition();

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

  const inputCls =
    "h-9 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

  return (
    <form onSubmit={onSubmit} className="space-y-6 rounded-lg border border-border p-6">
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label
            htmlFor="risk_per_trade_pct"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            Risk per trade (%)
          </label>
          <input
            id="risk_per_trade_pct"
            name="risk_per_trade_pct"
            type="number"
            step="0.1"
            min="0.1"
            max="100"
            required
            defaultValue={config.risk_per_trade_pct}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            % of capital risked per trade (R).
          </p>
        </div>
        <div>
          <label
            htmlFor="max_position_pct"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            Max position size (%)
          </label>
          <input
            id="max_position_pct"
            name="max_position_pct"
            type="number"
            step="0.5"
            min="0.5"
            max="100"
            required
            defaultValue={config.max_position_pct}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Max % of capital in a single position.
          </p>
        </div>
        <div className="sm:col-span-2">
          <label
            htmlFor="preferred_llm"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            Preferred LLM
          </label>
          <select
            id="preferred_llm"
            name="preferred_llm"
            defaultValue={config.preferred_llm}
            className={inputCls}
          >
            <option value="claude">Claude</option>
            <option value="openai">OpenAI</option>
            <option value="gemini">Gemini</option>
          </select>
        </div>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}
      {saved ? (
        <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
          Saved. The next plan will use the new values.
        </div>
      ) : null}

      <div>
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
