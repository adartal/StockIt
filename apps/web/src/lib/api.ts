import "server-only";

import { cookies } from "next/headers";

import type { components, paths } from "./api-schema";

export type Plan = components["schemas"]["Plan"];
export type PlanCreateRequest = components["schemas"]["PlanCreateRequest"];
export type Horizon = PlanCreateRequest["horizon"];

type CreatePlanOp = paths["/plans"]["post"];
type CreatePlanResponse =
  CreatePlanOp["responses"][200]["content"]["application/json"];

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SESSION_COOKIE_CANDIDATES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
];

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

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await readSessionToken();
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (token) headers.set("authorization", `Bearer ${token}`);

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

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
