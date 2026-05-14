import { apiFetch } from "@/lib/api";
import type { UserRiskConfig } from "@/lib/api-types";
import { SettingsForm } from "./settings-form";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let config: UserRiskConfig | null = null;
  let error: string | null = null;
  try {
    config = await apiFetch<UserRiskConfig>("/settings");
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load settings";
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Risk and provider preferences applied to every new plan.
        </p>
      </div>
      {error || !config ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error ?? "Failed to load settings"}
        </div>
      ) : (
        <SettingsForm initial={config} />
      )}
    </main>
  );
}
