"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2Icon, PlusIcon, XIcon, ZapIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { GenerationProgress } from "@/components/forms/GenerationProgress";
import { cn } from "@/lib/utils";

import { submitPlan } from "./actions";

const HORIZONS = [
  { value: "intraday", label: "Intraday", hint: "Same-day, technical-driven" },
  { value: "swing", label: "Swing", hint: "Days to weeks" },
  { value: "long_term", label: "Long term", hint: "Months to years" },
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

const fieldBoxCls =
  "group/field relative flex items-baseline gap-2 rounded-md border border-input bg-muted/40 px-4 py-3 transition-colors focus-within:border-primary focus-within:bg-card focus-within:ring-2 focus-within:ring-primary/20";
const fieldInputCls =
  "min-w-0 flex-1 bg-transparent font-display text-3xl font-semibold tracking-tight tabular-nums outline-none placeholder:font-display placeholder:font-normal placeholder:italic placeholder:text-muted-foreground/60 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";

export function PlanInputForm() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [pendingTicker, setPendingTicker] = useState("");
  const [showConstraints, setShowConstraints] = useState(false);

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
    setPendingTicker(values.ticker.toUpperCase());
    const toastId = toast.loading(
      `Briefing ${values.ticker.toUpperCase()} · this takes ~90s`,
    );
    startTransition(async () => {
      const result = await submitPlan({
        ticker: values.ticker,
        capital: values.capital,
        horizon: values.horizon,
        constraints: values.constraints || undefined,
      });

      if (!result.ok) {
        toast.error(`Could not generate plan: ${result.message}`, { id: toastId });
        return;
      }

      toast.success(`Plan ready for ${result.ticker}`, { id: toastId });

      if (result.planId) {
        router.push(`/plans/${result.planId}`);
      } else {
        toast.message("Plan saved, but the server didn't return an id.");
      }
    });
  };

  return (
    <>
      <GenerationProgress open={isPending} ticker={pendingTicker} />
      <section className="space-y-6">
        <header className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
            New brief
          </p>
          <h1 className="font-display text-2xl font-semibold leading-tight tracking-tight text-balance sm:text-3xl">
            What are we looking at today?
          </h1>
        </header>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-[1fr_1.3fr]">
            {/* Ticker */}
            <div className="space-y-1.5">
              <Label
                htmlFor="ticker"
                className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
              >
                Ticker
              </Label>
              <div className={fieldBoxCls}>
                <input
                  id="ticker"
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  placeholder="AAPL"
                  aria-invalid={Boolean(errors.ticker)}
                  className={fieldInputCls}
                  {...register("ticker", {
                    setValueAs: (v) =>
                      typeof v === "string" ? v.toUpperCase().trim() : v,
                  })}
                />
              </div>
              <p
                className={cn(
                  "text-xs",
                  errors.ticker ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {errors.ticker?.message ?? "A–Z, 1–5 characters."}
              </p>
            </div>

            {/* Capital */}
            <div className="space-y-1.5">
              <Label
                htmlFor="capital"
                className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
              >
                Capital
              </Label>
              <div className={fieldBoxCls}>
                <span
                  aria-hidden
                  className="font-display text-2xl font-semibold text-muted-foreground"
                >
                  $
                </span>
                <input
                  id="capital"
                  type="number"
                  inputMode="decimal"
                  min={100}
                  step={100}
                  placeholder="10,000"
                  aria-invalid={Boolean(errors.capital)}
                  className={fieldInputCls}
                  {...register("capital")}
                />
                <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                  USD
                </span>
              </div>
              <p
                className={cn(
                  "text-xs",
                  errors.capital ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {errors.capital?.message ?? "Used for position sizing."}
              </p>
            </div>
          </div>

          {/* Horizon — segmented control */}
          <div className="space-y-1.5">
            <Label className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              Horizon
            </Label>
            <RadioGroup
              value={horizon}
              onValueChange={(v) =>
                setValue("horizon", v as ParsedValues["horizon"], {
                  shouldValidate: true,
                })
              }
              className="inline-flex w-full overflow-hidden rounded-md border border-input bg-muted/40 p-0.5"
            >
              {HORIZONS.map((opt) => {
                const checked = horizon === opt.value;
                return (
                  <Label
                    key={opt.value}
                    htmlFor={`horizon-${opt.value}`}
                    title={opt.hint}
                    className={cn(
                      "flex flex-1 cursor-pointer items-center justify-center gap-2 rounded px-3 py-2 text-sm transition-colors",
                      checked
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                    )}
                  >
                    <RadioGroupItem
                      id={`horizon-${opt.value}`}
                      value={opt.value}
                      className="sr-only"
                    />
                    <span className="font-medium">{opt.label}</span>
                  </Label>
                );
              })}
            </RadioGroup>
            <p className="text-xs text-muted-foreground">
              {HORIZONS.find((h) => h.value === horizon)?.hint ??
                "Pick a holding window."}
            </p>
          </div>

          {/* Constraints — collapsed by default */}
          {showConstraints ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label
                  htmlFor="constraints"
                  className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground"
                >
                  Constraints · optional
                </Label>
                <button
                  type="button"
                  onClick={() => setShowConstraints(false)}
                  className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
                >
                  <XIcon className="size-3" strokeWidth={1.5} />
                  Hide
                </button>
              </div>
              <Textarea
                id="constraints"
                rows={2}
                placeholder="e.g. avoid earnings exposure, max 2% portfolio risk, no margin"
                aria-invalid={Boolean(errors.constraints)}
                className="resize-none font-mono text-sm"
                {...register("constraints")}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowConstraints(true)}
              className="group inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
            >
              <PlusIcon className="size-3" strokeWidth={1.5} />
              Add constraints
            </button>
          )}

          <div className="flex items-center justify-between gap-3 border-t border-border pt-5">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Typical · 90s
            </p>
            <Button type="submit" size="lg" disabled={isPending}>
              {isPending ? (
                <>
                  <Loader2Icon className="animate-spin" />
                  Briefing…
                </>
              ) : (
                <>
                  <ZapIcon strokeWidth={1.5} />
                  Run analysis
                </>
              )}
            </Button>
          </div>
        </form>
      </section>
    </>
  );
}
