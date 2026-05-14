import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function Thesis({ thesis }: { thesis: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Thesis</CardTitle>
      </CardHeader>
      <CardContent className="prose prose-sm max-w-none dark:prose-invert prose-a:text-primary prose-a:underline-offset-4">
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
      </CardContent>
    </Card>
  );
}
