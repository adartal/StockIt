import { redirect } from "next/navigation";

import { auth, signOut } from "../../auth";
import { Button } from "@/components/ui/button";
import { PlanInputForm } from "@/components/forms/plan-input-form";

export default async function Home() {
  const session = await auth();

  if (!session?.user?.email) {
    redirect("/login");
  }

  const email = session.user.email;

  return (
    <main className="flex min-h-screen flex-col bg-background">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold tracking-tight">StockIt</h1>
          <span className="text-xs text-muted-foreground">
            Personal portfolio-action engine
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {email}
          </span>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <Button type="submit" variant="ghost" size="sm">
              Sign out
            </Button>
          </form>
        </div>
      </header>

      <section className="flex flex-1 items-start justify-center px-4 py-10 sm:py-16">
        <PlanInputForm />
      </section>
    </main>
  );
}
