/* eslint-disable */
/**
 * AUTO-GENERATED. Do not edit by hand.
 * Run `packages/shared-types/generate.sh` after changing
 * `apps/api/app/pipeline/schema.py`.
 */

export interface AnalystOutput {
  findings: (string)[];
  confidence: number;
  key_metrics: Record<string, unknown>;
  citations: (Citation)[];
}

export interface Catalyst {
  date: string;
  description: string;
  kind: "earnings" | "macro" | "corporate" | "other";
}

export interface Citation {
  url: string;
  title: string;
  source: string;
  fetched_at: string;
}

export interface Entry {
  kind: "limit" | "market" | "stop_limit";
  levels: (string)[];
  conditions: string;
}

export interface ExitLevel {
  kind: "scale_out" | "time_stop" | "invalidation";
  price?: string | null;
  trigger: string;
  portion?: number | null;
}

export interface Plan {
  ticker: string;
  horizon: "intraday" | "swing" | "long_term";
  capital: string;
  generated_at: string;
  thesis: string;
  conviction: "low" | "medium" | "high";
  entry: Entry;
  sizing: Sizing;
  stop: Stop;
  exits: (ExitLevel)[];
  catalysts: (Catalyst)[];
  risk_flags: (RiskFlag)[];
  review_cadence: string;
  sources: (Citation)[];
}

export interface RiskFlag {
  severity: "info" | "warn";
  code: string;
  message: string;
}

export interface Sizing {
  risk_pct: number;
  shares: number;
  dollar_exposure: string;
  R_value: string;
}

export interface Stop {
  price: string;
  kind: "technical" | "atr" | "fixed_pct";
  rationale: string;
}
