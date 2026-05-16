import { ScrollTextIcon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SectionMarker } from "@/components/plan/SectionMarker";

export function Thesis({ thesis }: { thesis: string }) {
  return (
    <section className="reveal-up space-y-5">
      <SectionMarker label="Thesis" icon={ScrollTextIcon} />
      <article
        className="prose-editorial prose prose-stone max-w-[68ch] font-sans text-[15px] leading-[1.75] text-foreground dark:prose-invert prose-headings:font-display prose-headings:font-medium prose-headings:tracking-tight prose-h2:mt-8 prose-h2:border-b prose-h2:border-border prose-h2:pb-2 prose-h2:text-xl prose-h3:text-base prose-p:my-4 prose-a:text-primary prose-a:underline-offset-4 prose-strong:text-foreground prose-blockquote:border-l-2 prose-blockquote:border-primary prose-blockquote:not-italic prose-blockquote:text-muted-foreground"
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline underline-offset-4"
              >
                {children}
              </a>
            ),
          }}
        >
          {thesis || "_(no thesis provided)_"}
        </ReactMarkdown>
      </article>
    </section>
  );
}
