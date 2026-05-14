"use server";

import { revalidatePath } from "next/cache";
import { ApiError, patchSettings, type UserRiskConfig } from "@/lib/api";

export type SettingsResult =
  | { ok: true; data: UserRiskConfig }
  | { ok: false; error: string };

function describe(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as { detail?: string } | undefined;
    return body?.detail ?? e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export async function updateSettings(
  formData: FormData,
): Promise<SettingsResult> {
  const riskRaw = formData.get("risk_per_trade_pct");
  const maxRaw = formData.get("max_position_pct");
  const llm = formData.get("preferred_llm");

  const risk = riskRaw != null ? Number(riskRaw) : NaN;
  const max = maxRaw != null ? Number(maxRaw) : NaN;

  if (!Number.isFinite(risk) || risk <= 0 || risk > 100) {
    return { ok: false, error: "Risk per trade must be between 0 and 100." };
  }
  if (!Number.isFinite(max) || max <= 0 || max > 100) {
    return { ok: false, error: "Max position must be between 0 and 100." };
  }
  if (llm !== "claude" && llm !== "openai" && llm !== "gemini") {
    return { ok: false, error: "Preferred LLM must be claude, openai, or gemini." };
  }

  try {
    const data = await patchSettings({
      risk_per_trade_pct: risk,
      max_position_pct: max,
      preferred_llm: llm,
    });
    revalidatePath("/settings");
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: describe(e) };
  }
}
