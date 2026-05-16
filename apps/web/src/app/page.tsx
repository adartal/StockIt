import { redirect } from "next/navigation";

import { auth } from "../../auth";
import { PlanInputForm } from "@/components/forms/plan-input-form";
import { MarketStrip } from "@/components/dashboard/MarketStrip";
import { Tickertape } from "@/components/dashboard/Tickertape";
import { WatchlistPreview } from "@/components/dashboard/WatchlistPreview";
import { listWatchlist } from "@/lib/api";
import type { WatchlistItem } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const session = await auth();

  if (!session?.user?.email) {
    redirect("/login");
  }

  let items: WatchlistItem[] = [];
  try {
    items = await listWatchlist();
  } catch {
    items = [];
  }

  return (
    <>
      <Tickertape items={items} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10 sm:py-14">
        <div className="grid gap-12 lg:grid-cols-[1fr_320px]">
          <PlanInputForm />
          <div className="space-y-6">
            <WatchlistPreview items={items} />
          </div>
        </div>

        <div className="mt-14">
          <MarketStrip />
        </div>
      </main>
    </>
  );
}
