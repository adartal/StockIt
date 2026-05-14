"use server";

import { revalidatePath } from "next/cache";
import {
  addWatchlistItem,
  ApiError,
  deleteWatchlistItem,
  refreshWatchlistItem,
  type WatchlistItem,
} from "@/lib/api";

export type ActionResult<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function describe(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as { detail?: string } | undefined;
    return body?.detail ?? e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export async function addWatchlistAction(
  formData: FormData,
): Promise<ActionResult<WatchlistItem>> {
  const ticker = String(formData.get("ticker") ?? "").trim();
  if (!ticker) return { ok: false, error: "Ticker is required" };
  try {
    const data = await addWatchlistItem(ticker);
    revalidatePath("/watchlist");
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: describe(e) };
  }
}

export async function refreshWatchlistAction(
  id: string,
): Promise<ActionResult<{ revision_id: string; updated_at: string }>> {
  try {
    const rev = await refreshWatchlistItem(id);
    revalidatePath("/watchlist");
    return {
      ok: true,
      data: { revision_id: rev.id, updated_at: rev.created_at },
    };
  } catch (e) {
    return { ok: false, error: describe(e) };
  }
}

export async function deleteWatchlistAction(
  id: string,
): Promise<ActionResult<null>> {
  try {
    await deleteWatchlistItem(id);
    revalidatePath("/watchlist");
    return { ok: true, data: null };
  } catch (e) {
    return { ok: false, error: describe(e) };
  }
}
