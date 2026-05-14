import { cookies } from "next/headers";

import type { Plan } from "@/types/generated";

export interface Note {
  id: string;
  plan_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

const SESSION_COOKIE_NAMES = [
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

async function bearerToken(): Promise<string | null> {
  const jar = await cookies();
  for (const name of SESSION_COOKIE_NAMES) {
    const c = jar.get(name);
    if (c?.value) return c.value;
  }
  return null;
}

async function authedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await bearerToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
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
