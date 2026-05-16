"use client";

import { useState, useTransition } from "react";
import { NotebookPenIcon } from "lucide-react";

import { SectionMarker } from "@/components/plan/SectionMarker";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export interface NoteView {
  id: string;
  body: string;
  created_at: string;
}

export function Notes({
  planId,
  initialNotes,
}: {
  planId: string;
  initialNotes: NoteView[];
}) {
  const [notes, setNotes] = useState(initialNotes);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    setError(null);
    startTransition(async () => {
      try {
        const res = await fetch(`/api/plans/${planId}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: trimmed }),
        });
        if (!res.ok) throw new Error(`POST failed: ${res.status}`);
        const note: NoteView = await res.json();
        setNotes((prev) => [...prev, note]);
        setText("");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    });
  }

  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label="Margin notes" icon={NotebookPenIcon} />

      {notes.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          No notes yet. Use this space for observations, follow-ups, and
          post-mortems.
        </p>
      ) : (
        <ul className="space-y-4">
          {notes.map((n) => (
            <li key={n.id} className="border-l-2 border-primary/60 pl-4">
              <p className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground">
                {n.body}
              </p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                {new Date(n.created_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={onSubmit} className="space-y-2 print:hidden">
        <Textarea
          placeholder="Add a note (observations, follow-ups, post-mortems)…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          disabled={pending}
          className="font-mono text-sm"
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" size="sm" disabled={pending || !text.trim()}>
            {pending ? "Adding…" : "Add note"}
          </Button>
        </div>
      </form>
    </section>
  );
}
