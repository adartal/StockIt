# StockIt

Personal portfolio-action engine. Takes `ticker + capital + horizon`, runs a structured
LLM-driven due-diligence pipeline across fundamentals, technicals, news, and macro, and
outputs an executable trading plan (thesis, entries, sizing, stops, exits, catalysts).

US equities + ETFs only. Single-user, cloud-hosted with email magic-link auth. No broker
integration — plans are exported and executed manually.

See [ROADMAP.md](./ROADMAP.md) for milestones and the [approved plan](~/.claude/plans/i-have-an-idea-glimmering-puddle.md)
for architecture details.

## Layout

```
apps/
  api/                FastAPI + Python 3.12 (uv-managed)
  web/                Next.js 15 + TypeScript + Tailwind v4 + shadcn/ui
packages/
  shared-types/       TS types generated from pydantic (populated in M1)
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python toolchain)
- Node 20+ and [pnpm](https://pnpm.io/) 9+

## Run the API

```bash
cd apps/api
uv sync
uv run uvicorn app.main:app --reload
# health check
curl http://localhost:8000/health
```

## Run the web app

```bash
cd apps/web
pnpm install
pnpm dev
# http://localhost:3000
```

## Tests

```bash
cd apps/api && uv run pytest
cd apps/web && pnpm lint
```

## Status

Bootstrapped at M0. See [ROADMAP.md](./ROADMAP.md) for what's next.
