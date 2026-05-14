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
import type { ExitLevel } from "@/types/generated";

export function Exits({ exits }: { exits: ExitLevel[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Exits</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {exits.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">No exits defined.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kind</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Portion</TableHead>
                <TableHead>Trigger</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {exits.map((e, i) => (
                <TableRow key={i}>
                  <TableCell className="capitalize">
                    {e.kind.replace("_", " ")}
                  </TableCell>
                  <TableCell>{e.price ? `$${e.price}` : "—"}</TableCell>
                  <TableCell>
                    {e.portion != null ? `${(e.portion * 100).toFixed(0)}%` : "—"}
                  </TableCell>
                  <TableCell className="whitespace-normal">{e.trigger}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
