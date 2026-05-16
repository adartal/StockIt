import { getSettings, type UserRiskConfig } from "@/lib/api";
import { SettingsForm } from "./settings-form";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let config: UserRiskConfig | null = null;
  let error: string | null = null;
  try {
    config = await getSettings();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load settings";
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
      <header className="mb-10 space-y-3 border-b border-border pb-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Preferences
        </p>
        <h1 className="font-display text-5xl font-semibold leading-none tracking-tight">
          Trading rules
        </h1>
        <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
          The risk envelope and the model the desk uses to draft your briefs.
          Applied to every new plan, starting with the next one you run.
        </p>
      </header>
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
