# Frontend Stack Decisions (M8 preamble)

Stack baseline: Next.js 16.2.6, React 19.2.4, Tailwind 4, shadcn/ui (only `button` scaffolded today). No chart/markdown/PDF deps present.

## 1. shadcn/ui component picks

- **Structured form** (ticker, capital, horizon, constraints): `Form` (RHF + zod), `Input`, `Select` (horizon), `Slider` or `Input` for capital, `Textarea` for free-text constraints, `Checkbox`/`ToggleGroup` for boolean flags, `Button`. Use `Card` to group.
- **Plan render** (thesis, entry/sizing/stop, exits, catalysts, risk flags, citations): `Card` per section + `CardHeader`/`CardContent`, `Separator` between sections, `Badge` for risk flags, `Accordion` for collapsible citations, `Table` for exits/sizing rows, `HoverCard` for citation snippets.
- **Watchlist table with diff badges**: `Table` (with `@tanstack/react-table` headless) + `Badge` (variants for up/down/changed), `DropdownMenu` for row actions, `Input` for filter.
- **Settings form**: `Form`, `Switch`, `Input`, `Select`, `Tabs` for sections (Account / Notifications / API), `Button`.

## 2. Chart library — recommend `lightweight-charts`

- `recharts`: easy with Next.js but heavy (~150 KB gz), poor candlestick + indicator overlay support, slow on 1k+ bars.
- `visx`: powerful but you build everything; no built-in indicator overlays.
- **`lightweight-charts`** (TradingView, Apache-2.0): ~45 KB gz, native candlestick/area/line, multiple panes and overlay series (SMA/EMA/RSI/volume), excellent perf. Integrate as a client-only component (`'use client'` + `dynamic(..., { ssr: false })`). Indicators computed in app code (or via `technicalindicators`).

## 3. Export-to-PDF — recommend pure `@media print` CSS + `react-to-print`

Plan render is mostly text/table/badge; the browser already renders it well. Add `@media print` Tailwind utilities to hide nav/buttons, force section page-breaks, and inline citations. Use `react-to-print` only as a trigger wrapper (one-click print) — no canvas rasterization, fonts/links stay selectable. Avoid `html2pdf`/`jspdf`: they rasterize via html2canvas, blur charts, and bloat the bundle.

## 4. Markdown — recommend `react-markdown` + `remark-gfm`

Thesis is user-/LLM-generated short markdown. `react-markdown` gives a safe React-tree render (no `dangerouslySetInnerHTML`), per-element component overrides (map `a` → `Link`, `code` → shadcn style), and pairs with `remark-gfm` for tables/strikethrough. `marked` returns HTML (needs sanitizer). MDX is overkill — thesis content is data, not authored pages.
