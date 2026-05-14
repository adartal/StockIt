"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { submitPlan } from "./actions";

const HORIZONS = [
  {
    value: "intraday",
    label: "Intraday",
    hint: "Same-day, technical-driven",
  },
  {
    value: "swing",
    label: "Swing",
    hint: "Days to weeks",
  },
  {
    value: "long_term",
    label: "Long term",
    hint: "Months to years",
  },
] as const;

const schema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "Ticker is required")
    .max(5, "Tickers are 1–5 characters")
    .regex(/^[A-Za-z]{1,5}$/, "Use A–Z only, 1–5 characters"),
  capital: z.coerce
    .number({ message: "Enter a number" })
    .min(100, "Minimum capital is $100")
    .max(10_000_000, "That's a lot — capped at $10,000,000"),
  horizon: z.enum(["intraday", "swing", "long_term"]),
  constraints: z.string().trim().max(2000).optional().or(z.literal("")),
});

type ParsedValues = z.output<typeof schema>;

export function PlanInputForm() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      ticker: "",
      capital: 10000,
      horizon: "swing",
      constraints: "",
    },
    mode: "onTouched",
  });

  const horizon = watch("horizon");

  const onSubmit = (values: ParsedValues) => {
    const toastId = toast.loading(
      `Generating plan for ${values.ticker.toUpperCase()}… (up to 90s)`,
    );
    startTransition(async () => {
      const result = await submitPlan({
        ticker: values.ticker,
        capital: values.capital,
        horizon: values.horizon,
        constraints: values.constraints || undefined,
      });

      if (!result.ok) {
        toast.error(`Could not generate plan: ${result.message}`, {
          id: toastId,
        });
        return;
      }

      toast.success(`Plan ready for ${result.ticker}`, { id: toastId });

      if (result.planId) {
        router.push(`/plans/${result.planId}`);
      } else {
        // Fall back if the API ever omits the id — keep the user on the home
        // page rather than navigating somewhere broken.
        toast.message("Plan saved, but the server didn't return an id.");
      }
    });
  };

  return (
    <Card className="w-full max-w-xl">
      <CardHeader>
        <CardTitle>New trading plan</CardTitle>
        <CardDescription>
          Pick a ticker, set your capital, choose a horizon. We&rsquo;ll
          synthesize a plan with entries, sizing, stops, and risk flags.
        </CardDescription>
      </CardHeader>

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <CardContent className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="ticker">Ticker</Label>
            <Input
              id="ticker"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="AAPL"
              aria-invalid={Boolean(errors.ticker)}
              {...register("ticker", {
                setValueAs: (v) =>
                  typeof v === "string" ? v.toUpperCase().trim() : v,
              })}
            />
            {errors.ticker ? (
              <p className="text-xs text-destructive">{errors.ticker.message}</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Uppercase letters, 1–5 characters.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="capital">Capital (USD)</Label>
            <Input
              id="capital"
              type="number"
              inputMode="decimal"
              min={100}
              step={100}
              placeholder="10000"
              aria-invalid={Boolean(errors.capital)}
              {...register("capital")}
            />
            {errors.capital ? (
              <p className="text-xs text-destructive">
                {errors.capital.message}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Minimum $100. Used for position sizing.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Horizon</Label>
            <RadioGroup
              value={horizon}
              onValueChange={(v) =>
                setValue("horizon", v as ParsedValues["horizon"], {
                  shouldValidate: true,
                })
              }
              className="grid gap-2 sm:grid-cols-3"
            >
              {HORIZONS.map((opt) => (
                <Label
                  key={opt.value}
                  htmlFor={`horizon-${opt.value}`}
                  className="flex cursor-pointer items-start gap-2 rounded-lg border border-input bg-background p-3 hover:bg-muted/50 has-data-checked:border-primary has-data-checked:bg-primary/5"
                >
                  <RadioGroupItem
                    id={`horizon-${opt.value}`}
                    value={opt.value}
                  />
                  <span className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium">{opt.label}</span>
                    <span className="text-xs text-muted-foreground">
                      {opt.hint}
                    </span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
            {errors.horizon ? (
              <p className="text-xs text-destructive">
                {errors.horizon.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="constraints">
              Constraints{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Textarea
              id="constraints"
              rows={3}
              placeholder="e.g. avoid earnings exposure, max 2% portfolio risk, no margin"
              aria-invalid={Boolean(errors.constraints)}
              {...register("constraints")}
            />
            {errors.constraints ? (
              <p className="text-xs text-destructive">
                {errors.constraints.message}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Free text passed through to the synthesizer.
              </p>
            )}
          </div>
        </CardContent>

        <CardFooter className="flex items-center justify-end gap-3">
          <Button type="submit" size="lg" disabled={isPending}>
            {isPending ? (
              <>
                <Loader2Icon className="animate-spin" />
                Generating…
              </>
            ) : (
              "Generate plan"
            )}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
