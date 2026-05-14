import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Catalyst } from "@/types/generated";

export function Catalysts({ catalysts }: { catalysts: Catalyst[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Catalysts</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {catalysts.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">
            No catalysts identified.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {catalysts.map((c, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">{c.date}</TableCell>
                  <TableCell className="capitalize">{c.kind}</TableCell>
                  <TableCell className="whitespace-normal">
                    {c.description}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
