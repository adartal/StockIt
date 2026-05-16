"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { MoonIcon, SunIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

function subscribe() {
  return () => {};
}

function getSnapshot() {
  return true;
}

function getServerSnapshot() {
  return false;
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const isDark = resolvedTheme === "dark";
  const label = mounted
    ? isDark
      ? "Switch to light"
      : "Switch to dark"
    : "Toggle theme";

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="size-8"
    >
      <span className="sr-only">{label}</span>
      {mounted ? (
        isDark ? (
          <SunIcon className="size-4" strokeWidth={1.5} />
        ) : (
          <MoonIcon className="size-4" strokeWidth={1.5} />
        )
      ) : (
        <SunIcon className="size-4 opacity-0" strokeWidth={1.5} />
      )}
    </Button>
  );
}
