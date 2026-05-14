"use client";

import { Button } from "@/components/ui/button";
import { planToMarkdown } from "@/lib/plan-to-markdown";
import type { Plan } from "@/types/generated";

function download(filename: string, mime: string, content: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ExportButtons({ plan }: { plan: Plan }) {
  const baseName = `${plan.ticker}-${plan.horizon}-${plan.generated_at.slice(0, 10)}`;

  return (
    <div className="flex flex-wrap items-center gap-2 print:hidden">
      <Button
        variant="outline"
        onClick={() =>
          download(`${baseName}.md`, "text/markdown;charset=utf-8", planToMarkdown(plan))
        }
      >
        Download .md
      </Button>
      <Button
        variant="outline"
        onClick={() =>
          download(
            `${baseName}.json`,
            "application/json;charset=utf-8",
            JSON.stringify(plan, null, 2),
          )
        }
      >
        Download .json
      </Button>
      <Button
        variant="outline"
        onClick={() => {
          const prev = document.title;
          document.title = baseName;
          window.print();
          document.title = prev;
        }}
      >
        Print / Save PDF
      </Button>
    </div>
  );
}
