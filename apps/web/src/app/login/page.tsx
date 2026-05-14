import { CircleAlertIcon, MailCheckIcon } from "lucide-react";

import { signIn } from "../../../auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type SearchParams = Promise<{ check?: string; error?: string }>;

function errorMessage(error: string | undefined): string | null {
  if (!error) return null;
  if (error === "AccessDenied") return "This email isn't on the allowlist.";
  return "Sign-in failed. Please try again.";
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const checkEmail = params.check === "email";
  const error = errorMessage(params.error);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-semibold tracking-tight">
            StockIt
          </CardTitle>
          <CardDescription>
            Sign in with a magic link sent to your email.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {checkEmail ? (
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm">
              <MailCheckIcon className="mt-0.5 size-4 text-muted-foreground" />
              <span>
                Check your email for a sign-in link. It expires in 10 minutes.
              </span>
            </div>
          ) : null}

          {error ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
            >
              <CircleAlertIcon className="mt-0.5 size-4" />
              <span>{error}</span>
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
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="you@example.com"
              />
            </div>
            <Button type="submit" className="w-full" size="lg">
              Send magic link
            </Button>
          </form>

          <p className="text-center text-xs text-muted-foreground">
            Access is limited to allowlisted email addresses.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
