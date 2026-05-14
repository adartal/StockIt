"use server";

import { ApiError, createPlan, type Horizon } from "@/lib/api";

export type SubmitPlanInput = {
  ticker: string;
  capital: number;
  horizon: Horizon;
  constraints?: string;
};

export type SubmitPlanResult =
  | { ok: true; planId?: string; ticker: string }
  | { ok: false; status: number | null; message: string };

export async function submitPlan(
  input: SubmitPlanInput,
): Promise<SubmitPlanResult> {
  try {
    // The backend's PlanCreateRequest does not currently accept `constraints`,
    // and the Plan schema is `extra="forbid"`, so we don't forward it as a
    // top-level field. The form keeps the textarea for parity with the M8a
    // spec; when the synth contract exposes a constraints input the client
    // can pass it through here.
    const plan = await createPlan({
      ticker: input.ticker.toUpperCase().trim(),
      horizon: input.horizon,
      capital: input.capital,
    });
    return {
      ok: true,
      planId: plan.id,
      ticker: plan.ticker,
    };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, status: err.status, message: err.message };
    }
    const message = err instanceof Error ? err.message : "Unknown error";
    return { ok: false, status: null, message };
  }
}
