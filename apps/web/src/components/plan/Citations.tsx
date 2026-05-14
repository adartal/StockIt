import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Citation } from "@/types/generated";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

export function Citations({ sources }: { sources: Citation[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Citations</CardTitle>
      </CardHeader>
      <CardContent>
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">No citations.</p>
        ) : (
          <ol className="space-y-2 text-sm">
            {sources.map((s, i) => (
              <li key={i} className="flex flex-col gap-0.5">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline underline-offset-4"
                >
                  [{i + 1}] {s.title}
                </a>
                <span className="text-xs text-muted-foreground">
                  {s.source} · {fmtDate(s.fetched_at)}
                  <span className="print:inline hidden"> · {s.url}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
