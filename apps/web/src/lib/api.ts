import "server-only";

import { cookies } from "next/headers";

import type { components, paths } from "./api-schema";

export type Plan = components["schemas"]["Plan"];
export type PlanCreateRequest = components["schemas"]["PlanCreateRequest"];
export type Horizon = PlanCreateRequest["horizon"];

type CreatePlanOp = paths["/plans"]["post"];
type CreatePlanResponse =
  CreatePlanOp["responses"][200]["content"]["application/json"];

export interface Note {
  id: string;
  plan_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItem {
  id: string;
  ticker: string;
  last_plan_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlanRevision {
  id: string;
  plan_id: string;
  created_at: string;
  payload: Record<string, unknown>;
  diff_json: Record<string, unknown>;
}

export interface UserRiskConfig {
  risk_per_trade_pct: number;
  max_position_pct: number;
  preferred_llm: "claude" | "openai" | "gemini";
}

const SESSION_COOKIE_CANDIDATES = [
  "__Secure-authjs.session-token",
  "authjs.session-token",
];

export function apiBaseUrl(): string {
  return (
    process.env.API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  );
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function readSessionToken(): Promise<string | null> {
  const jar = await cookies();
  for (const name of SESSION_COOKIE_CANDIDATES) {
    const value = jar.get(name)?.value;
    if (value) return value;
  }
  return null;
}

async function authedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await readSessionToken();
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (token) headers.set("authorization", `Bearer ${token}`);
  return fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await authedFetch(path, init);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => "");
    }
    const message =
      (typeof detail === "object" &&
        detail !== null &&
        "detail" in detail &&
        typeof (detail as { detail: unknown }).detail === "string" &&
        (detail as { detail: string }).detail) ||
      res.statusText ||
      `Request failed with status ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// The OpenAPI response model is `Plan`, but the persisted row has an id we
// rely on to redirect to the plan page. Treat id as optional so the client
// keeps compiling if the API ever drops it.
export type CreatedPlan = CreatePlanResponse & { id?: string };

export async function createPlan(
  input: PlanCreateRequest,
): Promise<CreatedPlan> {
  return apiFetch<CreatedPlan>("/plans", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getPlan(planId: string): Promise<Plan | null> {
  const res = await authedFetch(`/plans/${planId}`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`GET /plans/${planId} failed: ${res.status}`);
  }
  return (await res.json()) as Plan;
}

export async function listNotes(planId: string): Promise<Note[]> {
  const res = await authedFetch(`/plans/${planId}/notes`);
  if (!res.ok) {
    throw new Error(`GET /plans/${planId}/notes failed: ${res.status}`);
  }
  return (await res.json()) as Note[];
}

export async function createNote(
  planId: string,
  text: string,
): Promise<Note> {
  const res = await authedFetch(`/plans/${planId}/notes`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    throw new Error(`POST /plans/${planId}/notes failed: ${res.status}`);
  }
  return (await res.json()) as Note;
}

export async function listWatchlist(): Promise<WatchlistItem[]> {
  return apiFetch<WatchlistItem[]>("/watchlist");
}

export async function addWatchlistItem(ticker: string): Promise<WatchlistItem> {
  return apiFetch<WatchlistItem>("/watchlist", {
    method: "POST",
    body: JSON.stringify({ ticker }),
  });
}

export async function deleteWatchlistItem(id: string): Promise<void> {
  await apiFetch<void>(`/watchlist/${id}`, { method: "DELETE" });
}

export async function refreshWatchlistItem(id: string): Promise<PlanRevision> {
  return apiFetch<PlanRevision>(`/watchlist/${id}/refresh`, { method: "POST" });
}

export async function getSettings(): Promise<UserRiskConfig> {
  return apiFetch<UserRiskConfig>("/settings");
}

export async function patchSettings(
  patch: Partial<UserRiskConfig>,
): Promise<UserRiskConfig> {
  return apiFetch<UserRiskConfig>("/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
