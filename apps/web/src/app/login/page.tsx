import { signIn } from "../../../auth";

type SearchParams = Promise<{ check?: string; error?: string }>;

export default async function LoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const checkEmail = params.check === "email";
  const error = params.error;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-12">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-2 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">StockIt</h1>
          <p className="text-sm text-muted-foreground">
            Sign in with a magic link sent to your email.
          </p>
        </div>

        {checkEmail ? (
          <div className="rounded-md border border-border bg-muted/40 p-4 text-sm">
            Check your email for a sign-in link.
          </div>
        ) : null}

        {error ? (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            Sign-in failed. {error === "AccessDenied"
              ? "This email is not on the allowlist."
              : "Please try again."}
          </div>
        ) : null}

        <form
          action={async (formData) => {
            "use server";
            await signIn("resend", {
              email: String(formData.get("email") ?? ""),
              redirectTo: "/",
            });
          }}
          className="space-y-3"
        >
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@example.com"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            type="submit"
            className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90"
          >
            Send magic link
          </button>
        </form>
      </div>
    </main>
  );
}
