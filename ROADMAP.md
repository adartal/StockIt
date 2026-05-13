# StockIt — Development Roadmap

Companion to [the approved plan](~/.claude/plans/i-have-an-idea-glimmering-puddle.md). This document defines milestones, dependencies, and how to parallelize the work using Claude Code.

Worker labels:
- **GP** — `general-purpose` Claude Code subagent (writes code)
- **EX** — `Explore` subagent (read-only research/inventory)
- **PL** — `Plan` subagent (architecture spike, no edits)
- **YOU** — actions only a human can do (provision keys, create cloud accounts, paste secrets)

---

## Milestones

### M0 — Bootstrap (sequential, blocks everything)
- **Worker:** 1× GP
- **Depends on:** nothing
- **Parallel with:** nothing
- **Deliverables:** monorepo (`apps/web`, `apps/api`, `packages/shared-types`); `apps/api` with `pyproject.toml`, ruff, mypy, FastAPI hello-world, alembic init; `apps/web` with Next.js 15 + TS + Tailwind + shadcn/ui; `.env.example` files; README; minimal CI (lint + typecheck).
- **You:** create the GitHub repo, decide Postgres hosting region.

### M1 — Core schemas & contracts (sequential, unblocks everything)
- **Worker:** 1× GP
- **Depends on:** M0
- **Parallel with:** nothing
- **Deliverables:** `apps/api/app/pipeline/schema.py` (`Plan`, `Entry`, `Sizing`, `Stop`, `ExitLevel`, `Catalyst`, `RiskFlag`, `Citation`, `AnalystOutput`); `apps/api/app/models.py` SQLAlchemy (`User`, `Plan`, `PlanRevision`, `WatchlistItem`, `Note`, `DataCache`, `UserRiskConfig`); first alembic migration; `packages/shared-types` TS generation via `datamodel-code-generator`.
- **Critical:** every downstream worker codes against these types. Lock them down before fanning out.

### M2 — Data layer (4 fetchers, fully parallelizable)
- **Workers:** 1× EX upfront, then up to 4× GP in parallel
- **Depends on:** M1
- **Parallel with:** M3, M7
- **EX first:** one read-only pass surveying yfinance, Alpha Vantage, NewsAPI, FRED, EDGAR rate-limits and quirks. ~200 word report.
- **Then 4 GPs in parallel, one per fetcher:**
  - M2a — `pipeline/data/prices.py` (yfinance + Alpha Vantage intraday fallback) + shared `Cached` decorator
  - M2b — `pipeline/data/fundamentals.py` (EDGAR via `edgartools` + yfinance basics)
  - M2c — `pipeline/data/news.py` (NewsAPI + RSS via `feedparser`, dedupe by URL)
  - M2d — `pipeline/data/macro.py` (FRED via `fredapi`, sector ETF prices)
- **Dependency note:** the `Cached` wrapper lives in M2a — M2b/c/d wait for its interface to land, then proceed.

### M3 — LLM provider abstraction (parallel with M2)
- **Worker:** 1× GP
- **Depends on:** M1
- **Parallel with:** M2, M7
- **Deliverables:** `llm/provider.py` (`LLMProvider.complete_structured` using `instructor`); `llm/claude.py` with prompt caching; `llm/openai.py`, `llm/gemini.py` fallbacks; provider-fallback policy on rate-limit/5xx; smoke test against each provider.
- **You:** provision Anthropic, OpenAI, Gemini API keys.

### M4 — Analyst stages (4 modules, fully parallelizable)
- **Workers:** 1× PL upfront (recommended), then up to 4× GP in parallel
- **Depends on:** M1, M2, M3
- **Parallel with:** M5a (risk module)
- **PL first:** design the analyst prompt template (system block, output JSON schema, horizon-adaptive instructions). Prevents 4 GPs inventing 4 different prompt styles.
- **Then 4 GPs in parallel:**
  - M4a — `analysts/fundamentals.py`
  - M4b — `analysts/technicals.py` (uses `pandas-ta` for RSI/MACD/ATR/MAs)
  - M4c — `analysts/news.py`
  - M4d — `analysts/macro.py`
- Each module: prompt template, `AnalystOutput` pydantic schema, `async def run(ticker, data, horizon) -> AnalystOutput`. Each emits a `confidence` 0–1 and citations with URLs.

### M5 — Synthesizer + risk post-processor
- **Workers:** 2× GP in parallel
- **Depends on:** M1 (risk); M3 + analyst output schema (synth)
- **Parallel with:** M4 (the risk module specifically)
- **Deliverables:**
  - M5a — `pipeline/risk.py` (deterministic stop-required + R-sizing + sector flag) + `tests/test_risk.py`. Starts as soon as M1 is done.
  - M5b — `pipeline/synth.py` (single LLM call, strict JSON, one retry on validation failure). Needs M3 and the `AnalystOutput` schema from the M4 prompt-design spike.

### M6 — Orchestrator + API routes (sequential, integration point)
- **Worker:** 1× GP
- **Depends on:** M2, M4, M5
- **Parallel with:** M7
- **Deliverables:** `pipeline/orchestrator.py` (`asyncio.gather` analysts → synth → risk → persist `Plan`); `routes/plans.py` (`POST /plans`, `GET /plans/:id`, `GET /plans?ticker=`); `routes/watchlist.py` (CRUD + `POST /watchlist/:id/refresh`); `routes/notes.py`. Export OpenAPI spec for the frontend.

### M7 — Auth (independent, parallel with most things)
- **Worker:** 1× GP
- **Depends on:** M0
- **Parallel with:** M2, M3, M4, M5, M6
- **Deliverables:** `apps/web` Auth.js v5 + Resend email magic link; `ALLOWED_EMAILS` env allowlist on both Auth.js and FastAPI; `apps/api/app/auth.py` JWT middleware (`python-jose`).
- **You:** create Resend account, configure sender domain.

### M8 — Frontend pages
- **Workers:** 1× EX upfront, then up to 3× GP in parallel
- **Depends on:** M6 OpenAPI (or a mocked client based on M1 shared types)
- **Parallel with:** M9
- **EX first:** inventory shadcn/ui components and chart libs (recharts vs visx vs lightweight-charts) for the plan render.
- **Then 3 GPs in parallel** (all consume the generated TS client from M6's OpenAPI):
  - M8a — `app/page.tsx` (input form) + `app/login/`
  - M8b — `app/plans/[id]/page.tsx` (plan render, markdown/JSON export, print-to-PDF)
  - M8c — `app/watchlist/page.tsx` + `app/settings/page.tsx` (risk config)

### M9 — Watchlist scheduler (parallel with M8)
- **Worker:** 1× GP
- **Depends on:** M6
- **Parallel with:** M8
- **Deliverables:** `app/scheduler.py` (APScheduler in FastAPI lifespan); daily 22:00 UTC job that refreshes data, re-runs synth with cached/refreshed analysts, writes `PlanRevision` diff vs previous.

### M10 — End-to-end verification
- **Worker:** 1× GP
- **Depends on:** M6, M7, M8, M9
- **Parallel with:** nothing
- **Deliverables:** execute the 9-step smoke test from the plan; fix what breaks; add `apps/api/tests/test_e2e_pipeline.py` for the AAPL/swing happy path.

### M11 — Deploy
- **Worker:** 1× GP + YOU
- **Depends on:** M10
- **Parallel with:** nothing
- **Deliverables:** Vercel project (`apps/web`); Fly.io app (`apps/api`); Neon/Supabase Postgres; alembic-on-deploy; production smoke test.
- **You:** create Vercel, Fly.io, Neon accounts and paste secrets (GP can't see them).

---

## Execution order with parallelism

```
Day-0 sequential:   M0 → M1
Then in parallel:   M2 (4 GPs) ║ M3 (1 GP) ║ M7 (1 GP)        — peak ~6 agents
Then in parallel:   M4 (4 GPs) ║ M5a risk (1 GP)
Then sequential:    M5b synth → M6
Then in parallel:   M8 (3 GPs) ║ M9 (1 GP)
Then sequential:    M10 → M11
```

---

## Parallelizing with Claude Code

There are two practical patterns. Use both — pattern A for tight fan-outs of small, well-scoped tasks; pattern B when you want to drive each stream interactively yourself.

### Pattern A — Subagents in a single Claude session

In your active Claude Code session, ask Claude to spawn multiple `general-purpose` subagents **in a single message**. Claude will issue several `Agent` tool calls in one turn, which the harness runs concurrently. Each can be isolated to its own git worktree so they don't fight over files.

Key mechanism: the `Agent` tool accepts `isolation: "worktree"`. When set, the subagent gets a temporary git worktree of the repo, makes its changes there, and the worktree's path + branch come back in the result. Branches that produced no changes are auto-cleaned. You then review and merge each branch into `main`.

How to invoke (example for the M2 fan-out, after M1 is merged on `main`):

> "Spawn 4 general-purpose agents in parallel, each in its own worktree (`isolation: worktree`). Agent 1 implements M2a from ROADMAP.md, agent 2 implements M2b, agent 3 M2c, agent 4 M2d. Each agent should branch from `main`, follow the schema in `apps/api/app/pipeline/schema.py`, and return the branch name + a summary of what it built. They should NOT touch each other's files."

Claude will then issue four parallel `Agent` calls in a single tool-use block. You'll get four branches to review.

Add `run_in_background: true` if a milestone is long-running and you want to keep working in the foreground; the harness notifies you when each agent completes (no polling needed).

Rules of thumb for pattern A:
- **Always lock the shared contract first** (M1) — let GPs touch only their assigned files.
- **One milestone per subagent.** Don't ask one subagent to do M2a+M2b; spawn two.
- **Brief each subagent like a cold colleague** — they don't see your conversation. Include: ROADMAP.md content for their milestone, file paths to create, schema references, and what "done" looks like.
- **Cap at ~4–6 parallel agents.** More than that and review becomes the bottleneck.
- **Use EX/PL subagents first** for milestones where ROADMAP says so (M2, M4, M8) — their short reports become context for the GPs that follow.

### Pattern B — Multiple Claude sessions in git worktrees

When you want to drive each stream interactively (review the diff in your editor, run the dev server, chat with Claude about it), use real `git worktree` directories and run a separate `claude` CLI in each:

```bash
# from the StockIt repo root, after M1 is on main
git worktree add ../stockit-m2a -b feat/m2a-prices
git worktree add ../stockit-m2b -b feat/m2b-fundamentals
git worktree add ../stockit-m2c -b feat/m2c-news
git worktree add ../stockit-m2d -b feat/m2d-macro
```

Open four terminals (or tmux panes / VS Code windows), `cd` into each worktree, run `claude` in each. Give each session the same briefing: "You're implementing M2a from ROADMAP.md. Branch is already checked out. Touch only files inside `apps/api/app/pipeline/data/prices.py` and tests."

When done in a worktree:

```bash
git push -u origin feat/m2a-prices
gh pr create     # if you want PR review flow
# or merge locally:
cd ../StockIt && git merge feat/m2a-prices
git worktree remove ../stockit-m2a
```

Use pattern B when:
- The milestone is non-trivial and you want to iterate (run tests, restart dev server, debug).
- You want PR-level review per milestone.
- The work spans many files and a quick `Agent` brief isn't enough context.

### Choosing between A and B

| Situation | Pattern |
|---|---|
| 4× small, well-specified fetchers (M2a–d) | A — single session, parallel subagents in worktrees |
| 4× analyst modules with prompt-engineering iteration (M4a–d) | B — one Claude session per analyst, you iterate on prompts |
| Long-running build that doesn't need babysitting (e.g. running test suite, scaffolding) | A with `run_in_background: true` |
| Frontend pages that need browser testing (M8a–c) | B — dev server per worktree on different ports |
| Architecture/prompt-design spikes (M4 prompt template) | A — single PL subagent, read-only |
| One-off research (M2/M8 inventory passes) | A — single EX subagent |

### Coordination rules across parallel work

1. **M1 is a hard barrier.** Don't fan out anything until pydantic schemas + DB models + TS type generation are merged on `main`.
2. **Schema changes after fan-out are expensive.** If you must change `Plan` mid-stream, rebase all parallel branches before they grow apart.
3. **One owner per file.** When briefing subagents in pattern A, explicitly say which paths each may touch. Forbid overlap.
4. **Merge tight.** Merge each parallel branch as soon as it's reviewed — don't let 4 branches diverge for days.
5. **Re-run M10 verification after every parallel merge cluster.** Catches integration bugs before they pile up.
6. **Secrets stay with you.** GP subagents can't see `.env`. They write `.env.example`; you fill the real `.env` once per worktree (or use a shared `direnv`/`mise` config outside the repo).

### Useful Claude Code features for this workflow

- `Agent` with `isolation: "worktree"` — the core parallelization primitive.
- `run_in_background: true` on `Agent` — for milestones that take many minutes; you'll be notified on completion.
- `/ultrareview` — multi-agent cloud review of a branch before you merge it. Useful for M5b (synth), M6 (orchestrator/routes), M10. User-invoked and billed; you trigger it manually.
- `/review` — lightweight PR review skill.
- `/security-review` — run before M11 deploy.
- Separate `claude` sessions per worktree — pattern B's foundation.

---

## Status tracker

Update this section as milestones complete.

- [ ] M0 — Bootstrap
- [ ] M1 — Core schemas & contracts
- [ ] M2 — Data layer (a/b/c/d)
- [ ] M3 — LLM provider abstraction
- [ ] M4 — Analyst stages (a/b/c/d)
- [ ] M5 — Synthesizer + risk post-processor
- [ ] M6 — Orchestrator + API routes
- [ ] M7 — Auth
- [ ] M8 — Frontend pages (a/b/c)
- [ ] M9 — Watchlist scheduler
- [ ] M10 — End-to-end verification
- [ ] M11 — Deploy
