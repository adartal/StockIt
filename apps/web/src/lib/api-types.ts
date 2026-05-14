export interface WatchlistItem {
  id: string;
  ticker: string;
  last_plan_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserRiskConfig {
  risk_per_trade_pct: number;
  max_position_pct: number;
  preferred_llm: "claude" | "openai" | "gemini";
}
