import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-12">
      <h1 className="text-5xl font-semibold tracking-tight">StockIt</h1>
      <p className="max-w-md text-center text-muted-foreground">
        Personal portfolio-action engine. Enter a ticker, capital, and horizon — get an
        executable trading plan.
      </p>
      <Button disabled>Coming soon</Button>
    </main>
  );
}
