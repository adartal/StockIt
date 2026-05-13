# StockIt — Per-Milestone Agent Briefings

One self-contained briefing per milestone. Copy the entire block (between the `---` rules) into a fresh `claude` session running inside the relevant worktree.

Each briefing assumes the agent has filesystem access to:
- `/Users/taladar/Documents/StockIt/ROADMAP.md` — milestone breakdown
- `/Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md` — approved product/architecture spec

If the agent can't read the `.claude/plans/...` path (some sandbox configs block it), tell it to fall back to ROADMAP.md — that file plus its own briefing is enough to do the work.

---

## M0 — Bootstrap

**Where to run:** in `/Users/taladar/Documents/StockIt` (no worktree yet — repo doesn't exist).

```
You are implementing milestone M0 (Bootstrap) of the StockIt project.

StockIt is a personal portfolio-action engine: takes ticker + capital + horizon, runs a structured LLM-driven due-diligence pipeline across fundamentals/technicals/news/macro, outputs an executable trading plan. Personal use, cloud-hosted with login, no broker integration in v1, US equities + ETFs only.

READ THESE FIRST:
- /Users/taladar/Documents/StockIt/ROADMAP.md
- /Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md (architecture details)

Deliverables for M0:
1. `git init` and create .gitignore (Python + Node + macOS)
2. Monorepo layout: apps/web/, apps/api/, packages/shared-types/
3. apps/api/: uv-managed Python 3.12 project with FastAPI, uvicorn, pydantic v2, ruff, mypy, pytest. alembic init (no migrations yet). app/main.py with GET /health → {"status":"ok"}. tests/test_health.py.
4. apps/web/: Next.js 15 (App Router, TypeScript) + Tailwind v4 + shadcn/ui initialized. Landing page with "StockIt" placeholder.
5. .env.example in both apps with placeholder keys (DATABASE_URL, ANTHROPIC_API_KEY, etc. — values blank)
6. Top-level README.md: what StockIt is, how to run api + web for dev, how to run tests.
7. .github/workflows/ci.yml: lint + typecheck + test on push and PR.

Acceptance:
- `cd apps/api && uv run uvicorn app.main:app --reload` serves /health
- `cd apps/web && pnpm dev` serves the landing page
- `uv run pytest` in apps/api passes
- `git log` shows commits on main

DO NOT: write pydantic Plan models (M1), set up databases (M1), set up auth (M7), pick LLM SDKs (M3).

When done, summarize: tool choices (uv/poetry, pnpm/npm), directory structure, anything I should sanity-check before M1.
```

---

## M1 — Core schemas & contracts

**Where to run:** same session as M0, or in `/Users/taladar/Documents/StockIt` on `main` after M0 is committed.

```
You are implementing milestone M1 (Core schemas & contracts) of the StockIt project.

Context files (read first):
- /Users/taladar/Documents/StockIt/ROADMAP.md
- /Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md (see "The Plan schema" section)

Pre-conditions: M0 merged on main. Verify apps/api/pyproject.toml and apps/web/package.json exist.

Deliverables:
1. apps/api/app/pipeline/schema.py — pydantic v2 models:
   - Plan: ticker, horizon (Literal['intraday','swing','long_term']), capital (Decimal), generated_at (datetime), thesis (str), conviction (Literal['low','medium','high']), entry, sizing, stop, exits (list[ExitLevel]), catalysts (list[Catalyst]), risk_flags (list[RiskFlag]), review_cadence (str), sources (list[Citation])
   - Entry: kind ('limit'|'market'|'stop_limit'), levels (list[Decimal]), conditions (str)
   - Sizing: risk_pct (float), shares (int), dollar_exposure (Decimal), R_value (Decimal — dollar risk per share)
   - Stop: price (Decimal), kind ('technical'|'atr'|'fixed_pct'), rationale (str)
   - ExitLevel: kind ('scale_out'|'time_stop'|'invalidation'), price (Optional[Decimal]), trigger (str), portion (Optional[float])
   - Catalyst: date (date), description (str), kind ('earnings'|'macro'|'corporate'|'other')
   - RiskFlag: severity ('info'|'warn'), code (str), message (str)
   - Citation: url (str), title (str), source (str), fetched_at (datetime)
   - AnalystOutput: findings (list[str]), confidence (float 0-1), key_metrics (dict[str, Any]), citations (list[Citation])
   Serialize Decimal as string in JSON.

2. apps/api/app/models.py — SQLAlchemy 2.0 async models:
   User, UserRiskConfig (risk_per_trade_pct default 1.0, max_position_pct default 10.0, preferred_llm default 'claude'), Plan (stores serialized Plan JSON as payload), PlanRevision (with diff_json), WatchlistItem (with last_plan_id FK), Note, DataCache (composite PK on key + source, with fetched_at + ttl_seconds).

3. apps/api/app/db.py — async engine + sessionmaker; reads DATABASE_URL from env, fallback sqlite+aiosqlite for dev.

4. apps/api/alembic/versions/ — first migration creating all tables. Verify `uv run alembic upgrade head` works against local Postgres AND sqlite.

5. packages/shared-types/:
   - generate.sh — runs datamodel-code-generator against apps/api/app/pipeline/schema.py → apps/web/src/types/generated.ts
   - README on when to re-run
   - Commit the generated file once

Acceptance:
- `uv run pytest` passes (include a round-trip test: Plan → JSON → Plan)
- `uv run alembic upgrade head` works on both sqlite and Postgres
- apps/web type-checks against the generated TS types

DO NOT: implement fetchers (M2), LLM code (M3), analyst logic (M4), risk rules (M5), routes (M6).

When done, summarize: every model field, sync vs async session decision, any schema simplifications you made.
```

---

## M2 (preamble) — EX agent: data-source survey

**Where to run:** any worktree, this is read-only. Use an `Explore` subagent or a quick session with no edits.

```
Read-only research task. Do NOT edit files.

Survey the free tiers of these market-data sources for the StockIt project (see /Users/taladar/Documents/StockIt/ROADMAP.md):
- yfinance (Python lib) — daily and intraday OHLCV
- Alpha Vantage free tier — intraday fallback
- NewsAPI free tier — news headlines
- FRED (fredapi) — macro series
- EDGAR via edgartools — 10-K/10-Q filings

For each, report:
1. Rate limits (requests/min, /day)
2. Auth requirement (API key or none)
3. Known gotchas (silent failures, schema quirks, throttling without errors)
4. Typical data freshness / delays
5. Practical reliability (do people complain about it? alternatives?)

Output: a single ~250-word report. No code. This becomes context for the M2a–d implementers.
```

---

## M2a — Prices fetcher + shared Cached wrapper

**Where to run:** `git worktree add ../stockit-m2a -b feat/m2a-prices`

```
You are implementing milestone M2a (Prices fetcher + shared Cached wrapper) of the StockIt project.

Context (read first):
- /Users/taladar/Documents/StockIt/ROADMAP.md (M2 section)
- /Users/taladar/Documents/StockIt/apps/api/app/pipeline/schema.py
- /Users/taladar/Documents/StockIt/apps/api/app/models.py (DataCache model)

Pre-conditions: M1 is merged on main. You branched from main.

Deliverables:
1. apps/api/app/pipeline/data/__init__.py
2. apps/api/app/pipeline/data/cache.py — `Cached` async decorator/wrapper:
   - Stores results in the DataCache table keyed by (key, source) with TTL
   - On cache hit within TTL, returns cached payload
   - On miss, calls the wrapped fetcher, stores result, returns it
   - Handles rate-limit errors by extending TTL (serve stale) with a logged warning
3. apps/api/app/pipeline/data/prices.py:
   - `async def fetch_ohlcv(ticker: str, interval: Literal['1m','5m','1h','1d','1wk'], lookback_days: int) -> pd.DataFrame`
   - Primary: yfinance. Fallback for intraday intervals (1m/5m): Alpha Vantage if env key set.
   - Returns DataFrame with columns: open, high, low, close, volume, indexed by timestamp (UTC).
   - All calls wrapped with Cached (TTL: 60s for 1m, 5min for 5m, 1h for 1h, 1d for 1d/1wk).
4. apps/api/tests/test_prices.py — unit tests with mocked yfinance.

Acceptance:
- `uv run pytest tests/test_prices.py` passes
- Manual smoke: in a python repl, `await fetch_ohlcv('AAPL', '1d', 365)` returns a populated DataFrame
- Second call within TTL hits the cache (verify with a log/print or test)

Files you may touch: apps/api/app/pipeline/data/__init__.py, cache.py, prices.py, apps/api/tests/test_prices.py.
Files you MUST NOT touch: anything outside apps/api/app/pipeline/data/, schema.py, models.py.

DO NOT: implement fundamentals/news/macro fetchers — those are M2b/c/d in parallel worktrees.

When done, commit on feat/m2a-prices, push, summarize the Cached interface signature so the M2b/c/d agents can build against it.
```

---

## M2b — Fundamentals fetcher

**Where to run:** `git worktree add ../stockit-m2b -b feat/m2b-fundamentals`, after M2a's Cached interface is merged on main.

```
You are implementing milestone M2b (Fundamentals fetcher) of the StockIt project.

Context: /Users/taladar/Documents/StockIt/ROADMAP.md, schema.py, models.py.
Pre-conditions: M2a merged on main (you need apps/api/app/pipeline/data/cache.py).

Deliverables:
1. apps/api/app/pipeline/data/fundamentals.py:
   - `async def fetch_fundamentals(ticker: str) -> FundamentalsBundle` (pydantic model — define it in this file)
   - FundamentalsBundle fields: sector, industry, market_cap, pe_ttm, pb, ps, profit_margin, revenue_growth_yoy, debt_to_equity, free_cash_flow_ttm, latest_10k_url, latest_10q_url, latest_10q_filed_at
   - Use yfinance for quick metrics, edgartools for 10-K/10-Q URLs and metadata.
   - Wrap with Cached (TTL: 24h for fundamentals — they rarely change intraday).
2. apps/api/tests/test_fundamentals.py — unit tests with mocked yfinance + edgartools.

Acceptance:
- Tests pass
- Manual smoke: `await fetch_fundamentals('AAPL')` returns a populated FundamentalsBundle with valid 10-K URL

Files you may touch: apps/api/app/pipeline/data/fundamentals.py, apps/api/tests/test_fundamentals.py.
Files you MUST NOT touch: cache.py, prices.py, news.py, macro.py, schema.py, models.py.

DO NOT: parse the actual 10-K text content — just metadata + URLs. The analyst stage (M4a) can fetch and parse content if needed.

When done, commit on feat/m2b-fundamentals, push, summarize the FundamentalsBundle fields.
```

---

## M2c — News fetcher

**Where to run:** `git worktree add ../stockit-m2c -b feat/m2c-news`, after M2a merged.

```
You are implementing milestone M2c (News fetcher) of the StockIt project.

Context: ROADMAP.md, schema.py, models.py.
Pre-conditions: M2a merged on main (Cached available).

Deliverables:
1. apps/api/app/pipeline/data/news.py:
   - `async def fetch_news(ticker: str, lookback_days: int = 30) -> list[NewsItem]` (NewsItem pydantic — define here)
   - NewsItem: url, title, source, published_at, summary (str, optional), sentiment_hint (Optional[float])
   - Sources: NewsAPI (if env key set) + Yahoo Finance RSS via feedparser (always available) + Google News RSS for the ticker.
   - Dedupe by canonical URL.
   - Wrap with Cached (TTL: 30min for news).
2. apps/api/tests/test_news.py.

Acceptance:
- Tests pass
- Manual smoke: `await fetch_news('AAPL', 7)` returns ≥5 deduplicated items.

Files you may touch: apps/api/app/pipeline/data/news.py, apps/api/tests/test_news.py.
Files you MUST NOT touch: anything else.

DO NOT: do LLM-based sentiment scoring — that's the news analyst (M4c). Only structural metadata + summary if the feed provides one.

When done, commit on feat/m2c-news, push, summarize the NewsItem fields.
```

---

## M2d — Macro fetcher

**Where to run:** `git worktree add ../stockit-m2d -b feat/m2d-macro`, after M2a merged.

```
You are implementing milestone M2d (Macro fetcher) of the StockIt project.

Context: ROADMAP.md, schema.py, models.py.
Pre-conditions: M2a merged on main.

Deliverables:
1. apps/api/app/pipeline/data/macro.py:
   - `async def fetch_macro_context(sector: str) -> MacroBundle` (MacroBundle pydantic — define here)
   - MacroBundle fields:
     - rates: dict with DGS2, DGS10 (FRED 2y and 10y treasury), latest values + 30-day delta
     - vix: float (latest VIX close)
     - sector_etf_ticker: str (e.g. 'XLK' for Information Technology)
     - sector_etf_perf_30d: float
     - spy_perf_30d: float
   - Use fredapi (env key required) for treasuries; yfinance for VIX, sector ETFs, SPY.
   - Map sector → ETF using a hardcoded dict (cover the 11 GICS sectors).
   - Wrap with Cached (TTL: 1h for macro).
2. apps/api/tests/test_macro.py.

Acceptance:
- Tests pass
- Manual smoke: `await fetch_macro_context('Information Technology')` returns a populated MacroBundle.

Files you may touch: apps/api/app/pipeline/data/macro.py, apps/api/tests/test_macro.py.
Files you MUST NOT touch: anything else.

When done, commit on feat/m2d-macro, push, summarize MacroBundle fields and the sector→ETF map.
```

---

## M3 — LLM provider abstraction

**Where to run:** `git worktree add ../stockit-m3 -b feat/m3-llm`, after M1 merged. Can run fully in parallel with all of M2.

```
You are implementing milestone M3 (LLM provider abstraction) of the StockIt project.

Context (read first):
- /Users/taladar/Documents/StockIt/ROADMAP.md (M3 section)
- /Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md
- /Users/taladar/Documents/StockIt/apps/api/app/pipeline/schema.py

Pre-conditions: M1 merged on main.

Deliverables:
1. apps/api/app/llm/__init__.py
2. apps/api/app/llm/provider.py — abstract base:
   - `class LLMProvider(Protocol)` with `async def complete_structured(messages, response_model: type[BaseModel], *, cache_blocks: list[str] | None = None, max_retries: int = 1) -> BaseModel`
   - Use the `instructor` library to handle structured output + pydantic validation + automatic retry on validation failure.
3. apps/api/app/llm/claude.py:
   - Anthropic SDK implementation
   - Apply prompt caching on system blocks (the `cache_blocks` argument)
   - Default model: claude-sonnet-4-6 for analyst calls, claude-opus-4-7 for synth (expose model as constructor arg)
4. apps/api/app/llm/openai.py — OpenAI implementation. Model: gpt-4o or current equivalent.
5. apps/api/app/llm/gemini.py — Google Gemini implementation. Model: gemini-2.5-pro or current equivalent.
6. apps/api/app/llm/router.py — `class LLMRouter` that takes a primary + ordered fallbacks; on rate-limit (429) or 5xx, falls through. Logs which provider answered.
7. apps/api/app/llm/config.py — reads ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY from env; instantiates only providers whose keys are present.
8. apps/api/tests/test_llm_router.py — uses fake providers to test the fallback policy.

Acceptance:
- Tests pass
- Manual smoke (with at least Anthropic key set): instantiate a router, ask it to return a 3-field pydantic object, verify it works.
- Manual smoke for fallback: kill Anthropic key, repeat — should fall through to OpenAI/Gemini.

Files you may touch: everything under apps/api/app/llm/ and apps/api/tests/test_llm_*.
Files you MUST NOT touch: schema.py, models.py, pipeline/.

DO NOT: write any analyst prompts or call into pipeline code — that's M4.

When done, push, summarize the LLMProvider interface signature and the router's fallback behavior.
```

---

## M4 (preamble) — PL agent: analyst prompt design spike

**Where to run:** read-only `Plan` subagent or a session with no edits. Run before M4a–d.

```
Architecture spike — NO code, design only. Output a markdown document at /Users/taladar/Documents/StockIt/docs/analyst-prompt-design.md.

Context: /Users/taladar/Documents/StockIt/ROADMAP.md, the approved plan at ~/.claude/plans/i-have-an-idea-glimmering-puddle.md, and apps/api/app/pipeline/schema.py (AnalystOutput).

Design the analyst prompt template used by all four analysts (fundamentals, technicals, news, macro). Decide:
1. System block structure: persona, JSON schema reminder, horizon-adaptive instructions (intraday vs swing vs long_term), bias guards ("don't recommend a position, just analyze").
2. User block structure: how to pass the ticker + horizon + data slice; which parts to mark as cache_blocks for prompt caching.
3. How citations are required (every claim must have a URL from the data passed in).
4. How confidence (0-1) should be calibrated: what does 0.3 vs 0.7 vs 0.9 mean?
5. Horizon-specific weighting hints per analyst.
6. What the synthesizer (M5b) will receive: just AnalystOutput summaries, never raw data.

Output the document with:
- A "template" section showing the exact prompt skeleton (with placeholders like {ticker}, {horizon}, {data_payload}).
- A "per-analyst overrides" section listing what each of the 4 analysts varies.
- Open questions if any.

This document is the source of truth for the four parallel M4 agents.
```

---

## M4a — Fundamentals analyst

**Where to run:** `git worktree add ../stockit-m4a -b feat/m4a-fundamentals-analyst`, after M2b + M3 merged and docs/analyst-prompt-design.md exists on main.

```
You are implementing milestone M4a (Fundamentals analyst) of the StockIt project.

Context (read all):
- /Users/taladar/Documents/StockIt/ROADMAP.md
- /Users/taladar/Documents/StockIt/docs/analyst-prompt-design.md (prompt template)
- apps/api/app/pipeline/schema.py (AnalystOutput)
- apps/api/app/pipeline/data/fundamentals.py (the data you'll receive)
- apps/api/app/llm/ (the provider abstraction)

Pre-conditions: M1, M2b, M3 merged. Analyst prompt design doc on main.

Deliverables:
1. apps/api/app/pipeline/analysts/__init__.py
2. apps/api/app/pipeline/analysts/fundamentals.py:
   - `async def run(ticker: str, data: FundamentalsBundle, horizon: Horizon, llm: LLMProvider) -> AnalystOutput`
   - Prompt follows docs/analyst-prompt-design.md, specialized for fundamentals:
     - For long_term: weight valuation, growth, balance sheet heavily
     - For swing: focus on near-term catalysts visible in fundamentals (earnings dates, guidance)
     - For intraday: minimal fundamentals contribution (one or two bullets max)
   - Returns AnalystOutput with findings, confidence (0-1), key_metrics (e.g. {"pe_ttm": 28.5, ...}), citations (10-K/10-Q URLs).
3. apps/api/tests/test_analyst_fundamentals.py — uses a fake LLMProvider that returns canned AnalystOutput; verifies the prompt-builder produces the expected structure.

Acceptance: tests pass.

Files you may touch: apps/api/app/pipeline/analysts/__init__.py, fundamentals.py, apps/api/tests/test_analyst_fundamentals.py.
Files you MUST NOT touch: other analysts (technicals/news/macro — running in parallel worktrees), schema.py, llm/, data/.

DO NOT: implement other analysts. Do not modify the prompt-design doc — if you find issues, leave a note in your PR description.

When done, push and summarize the prompt structure and the key_metrics keys you emit.
```

---

## M4b — Technicals analyst

**Where to run:** `git worktree add ../stockit-m4b -b feat/m4b-technicals-analyst`, after M2a + M3 + design doc merged.

```
You are implementing milestone M4b (Technicals analyst) of the StockIt project.

Context: ROADMAP.md, docs/analyst-prompt-design.md, schema.py, apps/api/app/pipeline/data/prices.py, apps/api/app/llm/.
Pre-conditions: M1, M2a, M3, design doc merged.

Deliverables:
1. apps/api/app/pipeline/analysts/technicals.py:
   - `async def run(ticker: str, data: pd.DataFrame, horizon: Horizon, llm: LLMProvider) -> AnalystOutput`
   - Before calling the LLM, compute indicators with pandas-ta: RSI(14), MACD, ATR(14), SMA(20/50/200), recent support/resistance (simple swing-high/low detection).
   - Pass the *indicators + last 60 bars summary* to the LLM, NOT the full OHLCV (token budget).
   - Horizon weighting: intraday and swing weight technicals heavily; long_term uses technicals only for entry timing.
   - key_metrics should include: rsi_14, atr_14, sma_50, sma_200, distance_from_52w_high_pct.
2. apps/api/tests/test_analyst_technicals.py with fake LLMProvider.

Acceptance: tests pass.

Files you may touch: apps/api/app/pipeline/analysts/technicals.py, apps/api/tests/test_analyst_technicals.py.
Files you MUST NOT touch: other analysts, schema.py, llm/, data/.

When done, push and summarize the indicator set + key_metrics keys.
```

---

## M4c — News analyst

**Where to run:** `git worktree add ../stockit-m4c -b feat/m4c-news-analyst`, after M2c + M3 + design doc merged.

```
You are implementing milestone M4c (News analyst) of the StockIt project.

Context: ROADMAP.md, docs/analyst-prompt-design.md, schema.py, apps/api/app/pipeline/data/news.py, apps/api/app/llm/.
Pre-conditions: M1, M2c, M3, design doc merged.

Deliverables:
1. apps/api/app/pipeline/analysts/news.py:
   - `async def run(ticker: str, data: list[NewsItem], horizon: Horizon, llm: LLMProvider) -> AnalystOutput`
   - Cluster news into themes (let the LLM do this in one pass) and emit findings about: dominant narratives, sentiment direction, recency-weighted importance, upcoming catalysts mentioned.
   - Filter: long_term considers ≤90 days, swing ≤30 days, intraday ≤7 days.
   - key_metrics: sentiment_score (-1..1), num_items, dominant_themes (list[str]).
   - Citations: include the source URLs cited by the LLM in findings.
2. apps/api/tests/test_analyst_news.py with fake LLMProvider.

Acceptance: tests pass.

Files you may touch: apps/api/app/pipeline/analysts/news.py, apps/api/tests/test_analyst_news.py.
Files you MUST NOT touch: other analysts, schema.py, llm/, data/.

When done, push and summarize the prompt structure + sentiment scoring rubric.
```

---

## M4d — Macro analyst

**Where to run:** `git worktree add ../stockit-m4d -b feat/m4d-macro-analyst`, after M2d + M3 + design doc merged.

```
You are implementing milestone M4d (Macro analyst) of the StockIt project.

Context: ROADMAP.md, docs/analyst-prompt-design.md, schema.py, apps/api/app/pipeline/data/macro.py, apps/api/app/llm/.
Pre-conditions: M1, M2d, M3, design doc merged.

Deliverables:
1. apps/api/app/pipeline/analysts/macro.py:
   - `async def run(ticker: str, data: MacroBundle, horizon: Horizon, llm: LLMProvider) -> AnalystOutput`
   - Findings cover: rate environment impact on the sector, sector momentum vs market, VIX regime (low/normal/high), relative strength.
   - For intraday: minimize macro contribution (one bullet); for swing/long_term: expand.
   - key_metrics: sector_relative_perf_30d, rates_regime ('easing'|'tightening'|'flat'), vix_regime.
2. apps/api/tests/test_analyst_macro.py with fake LLMProvider.

Acceptance: tests pass.

Files you may touch: apps/api/app/pipeline/analysts/macro.py, apps/api/tests/test_analyst_macro.py.
Files you MUST NOT touch: other analysts, schema.py, llm/, data/.

When done, push and summarize the prompt structure.
```

---

## M5a — Risk post-processor

**Where to run:** `git worktree add ../stockit-m5a -b feat/m5a-risk`, after M1 merged. Can run in parallel with all of M2/M3/M4.

```
You are implementing milestone M5a (Risk post-processor) of the StockIt project.

Context: ROADMAP.md (M5 section), apps/api/app/pipeline/schema.py, apps/api/app/models.py.
Pre-conditions: M1 merged. (Does NOT need M2/M3/M4 — pure deterministic logic on the Plan schema.)

Deliverables:
1. apps/api/app/pipeline/risk.py:
   - `def apply_risk_rules(plan: Plan, capital: Decimal, risk_config: UserRiskConfig, existing_watchlist: list[WatchlistItem], existing_plans: list[Plan]) -> tuple[Plan, list[RiskFlag]]`
   - Rule 1 (hard): if plan.stop is None or plan.stop.price >= plan.entry.levels[0] (for longs), raise RiskRuleViolation('stop_required'). The orchestrator will catch this and re-prompt synth once.
   - Rule 2 (override): compute shares = floor((capital * risk_config.risk_per_trade_pct / 100) / (entry - stop)). Override plan.sizing. Compute dollar_exposure = shares * entry.
   - Rule 3 (warn): if the new plan's sector matches sector of >2 existing watchlist tickers or open plans, append a RiskFlag(severity='warn', code='sector_concentration', message=...).
   - Rule 4 (warn): if dollar_exposure > capital * risk_config.max_position_pct / 100, append a RiskFlag(severity='warn', code='oversized_position').
2. apps/api/tests/test_risk.py — table-driven tests covering: missing stop, stop >= entry, R-sizing math, sector concentration, oversized position.

Acceptance: pytest passes with ≥6 test cases.

Files you may touch: apps/api/app/pipeline/risk.py, apps/api/tests/test_risk.py.
Files you MUST NOT touch: anything else.

When done, push and summarize the four rules + the RiskRuleViolation exception class.
```

---

## M5b — Synthesizer

**Where to run:** `git worktree add ../stockit-m5b -b feat/m5b-synth`, after M3 merged and the AnalystOutput schema from M1 + the prompt-design doc are on main. Can run in parallel with M4 if the design doc is finalized.

```
You are implementing milestone M5b (Synthesizer) of the StockIt project.

Context: ROADMAP.md, /Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md, docs/analyst-prompt-design.md, schema.py, apps/api/app/llm/.
Pre-conditions: M1, M3, design doc merged. (Does not strictly need M4 implementations — only the AnalystOutput schema.)

Deliverables:
1. apps/api/app/pipeline/synth.py:
   - `async def synthesize(ticker: str, horizon: Horizon, capital: Decimal, risk_config: UserRiskConfig, analyst_outputs: dict[str, AnalystOutput], llm: LLMProvider) -> Plan`
   - One LLM call (use Opus 4.7 by default for synthesis quality).
   - System block: PM persona, JSON schema reminder, "you receive only analyst summaries, never raw data".
   - User block: ticker, horizon, capital, all 4 AnalystOutputs serialized as JSON.
   - Output validated as a Plan pydantic model via instructor; one retry on validation failure with a clarifying note.
   - Must always emit a stop-loss; if it doesn't, the risk module (M5a) will catch it.
2. apps/api/tests/test_synth.py — with a fake LLMProvider returning a canned Plan; verifies the prompt builder passes correct inputs and validation works.

Acceptance: pytest passes; manual smoke with real Claude key produces a syntactically valid Plan for AAPL+swing+$10k+canned analyst outputs.

Files you may touch: apps/api/app/pipeline/synth.py, apps/api/tests/test_synth.py.
Files you MUST NOT touch: analyst modules, risk module, llm/, schema.py.

When done, push and summarize the synth prompt structure and retry behavior.
```

---

## M6 — Orchestrator + API routes

**Where to run:** `git worktree add ../stockit-m6 -b feat/m6-orchestrator`, after M2 (all of a/b/c/d), M4 (all of a/b/c/d), M5a, M5b merged.

```
You are implementing milestone M6 (Orchestrator + API routes) of the StockIt project.

Context: ROADMAP.md, schema.py, models.py, all of apps/api/app/pipeline/, apps/api/app/llm/.
Pre-conditions: M2, M4, M5 all merged.

Deliverables:
1. apps/api/app/pipeline/orchestrator.py:
   - `async def generate_plan(user_id, ticker, horizon, capital, risk_config) -> Plan`
   - Steps: parallel data fetch (asyncio.gather) → parallel analyst runs (asyncio.gather) → synth → risk → on RiskRuleViolation(stop_required), re-prompt synth once with a clarifying note → persist Plan → return.
2. apps/api/app/routes/plans.py:
   - POST /plans (body: ticker, horizon, capital) → Plan (200) or error (400/422/500)
   - GET /plans/{id} → Plan
   - GET /plans?ticker=AAPL → list[Plan]
3. apps/api/app/routes/watchlist.py:
   - POST /watchlist (body: ticker) → WatchlistItem
   - GET /watchlist → list[WatchlistItem]
   - DELETE /watchlist/{id} → 204
   - POST /watchlist/{id}/refresh → triggers a synth-only refresh, returns PlanRevision
4. apps/api/app/routes/notes.py:
   - POST /plans/{plan_id}/notes (body: text) → Note
   - GET /plans/{plan_id}/notes → list[Note]
5. apps/api/app/main.py — wire all routes, configure CORS for apps/web origin.
6. apps/api/app/openapi.py or a script that exports the OpenAPI JSON to packages/shared-types/openapi.json on demand.
7. apps/api/tests/test_routes_*.py — integration tests against a test DB.

Acceptance: tests pass; manual smoke: POST /plans for AAPL/swing/$10k returns a Plan in <90s with real LLM keys configured.

Files you may touch: orchestrator.py, routes/, main.py, the OpenAPI export script, tests.
Files you MUST NOT touch: analyst modules, data fetchers, llm/, risk.py, synth.py, schema.py, models.py.

DO NOT: implement auth here — M7 adds the middleware. For now, accept a hardcoded test user_id from a request header (TODO comment).

When done, push and summarize all endpoints + the orchestrator flow.
```

---

## M7 — Auth

**Where to run:** `git worktree add ../stockit-m7 -b feat/m7-auth`, after M0 merged. Parallel with everything M2–M6.

```
You are implementing milestone M7 (Auth) of the StockIt project.

Context: ROADMAP.md (M7 section).
Pre-conditions: M0 merged. M1 strongly recommended (you'll need the User model).

Deliverables:
1. apps/web:
   - Install Auth.js v5 (NextAuth)
   - Email magic-link provider via Resend
   - Allowlist via env var ALLOWED_EMAILS (comma-separated); reject signIn for any other address in the signIn callback
   - JWT session strategy; secret from AUTH_SECRET
   - apps/web/app/login/page.tsx — magic link form
   - apps/web/middleware.ts — gate everything except /login and /api/auth/*
2. apps/api:
   - apps/api/app/auth.py — FastAPI dependency that validates the Auth.js JWT (HS256 with AUTH_SECRET) and resolves to a User row (creating one on first sight). Exposes `CurrentUser = Annotated[User, Depends(...)]`.
   - Apply CurrentUser dependency on all routes in routes/plans.py, watchlist.py, notes.py if M6 is merged; otherwise leave the dependency ready for M6 to wire.
3. apps/api/tests/test_auth.py — verify a valid token resolves to User; invalid/expired/non-allowlisted rejects.

Acceptance: tests pass; manual smoke: log in with your allowlisted email → land on a dashboard; non-allowlisted email → rejected.

Files you may touch: apps/web (auth files only), apps/api/app/auth.py, apps/api/tests/test_auth.py. If M6 is merged, you may add the dependency to existing routes.
Files you MUST NOT touch: schema.py, pipeline/, llm/.

DO NOT: build the input form, the dashboard, or any plan-related UI — those are M8.

When done, push and summarize the Auth.js config and the FastAPI dependency signature. Tell me which env vars I need to set (AUTH_SECRET, RESEND_API_KEY, ALLOWED_EMAILS, EMAIL_FROM).
```

---

## M8 (preamble) — EX agent: frontend component inventory

**Where to run:** read-only `Explore` agent or no-edit session, before M8a–c.

```
Read-only inventory task. Do NOT edit files.

For the StockIt frontend (apps/web, Next.js 15 + shadcn/ui), report:
1. Which shadcn/ui components are best for: a structured form (ticker, capital, horizon, constraints), a sectioned plan render (thesis, entry/sizing/stop, exits, catalysts, risk flags, citations), a watchlist table with diff badges, a settings form.
2. Best free chart library for the plan render's price + indicator chart (compare recharts, visx, lightweight-charts). Recommend one based on: bundle size, ease of integration with Next.js, support for technical indicator overlays.
3. Export-to-PDF strategy: pure browser print-to-PDF via CSS @media print vs a library (react-to-print, html2pdf). Recommend.
4. Markdown rendering library for the thesis section (react-markdown vs marked vs MDX).

Output: ~300-word report saved at /Users/taladar/Documents/StockIt/docs/frontend-stack-decisions.md.
```

---

## M8a — Input form + login landing

**Where to run:** `git worktree add ../stockit-m8a -b feat/m8a-input-form`, after M6 (OpenAPI export) + M7 + docs/frontend-stack-decisions.md merged.

```
You are implementing milestone M8a (Input form + login) of the StockIt project.

Context: ROADMAP.md, docs/frontend-stack-decisions.md, packages/shared-types/openapi.json, apps/web/src/types/generated.ts.
Pre-conditions: M6, M7, frontend decisions doc merged.

Deliverables:
1. apps/web/src/lib/api.ts — generated TS client from openapi.json (use openapi-typescript or orval; pick what M8 EX recommended).
2. apps/web/app/page.tsx — gated home page; if logged in, renders the input form:
   - Fields: ticker (string, validated A-Z 1-5 chars), capital (number, min 100), horizon (radio: intraday/swing/long_term), optional constraints (textarea — free-text passed through to synth as a 'constraints' field).
   - Submit: POST /plans, show loading state (up to 90s), redirect to /plans/{id} on success.
3. apps/web/app/login/page.tsx — polish the M7 login form per the design system.
4. Loading + error states; toast notifications.

Acceptance: full flow works against a running backend: log in → submit AAPL/swing/$10k → land on plan page (M8b will render it).

Files you may touch: apps/web/app/page.tsx, app/login/page.tsx, src/lib/api.ts, any new components under src/components/forms/.
Files you MUST NOT touch: app/plans/, app/watchlist/, app/settings/, apps/api/.

DO NOT: implement the plan render page or watchlist — those are M8b/M8c.

When done, push and summarize the form fields and submit flow.
```

---

## M8b — Plan render page + export

**Where to run:** `git worktree add ../stockit-m8b -b feat/m8b-plan-render`, parallel with M8a.

```
You are implementing milestone M8b (Plan render + export) of the StockIt project.

Context: ROADMAP.md, docs/frontend-stack-decisions.md, apps/web/src/types/generated.ts.
Pre-conditions: M6, M7, frontend decisions doc merged.

Deliverables:
1. apps/web/app/plans/[id]/page.tsx — server-fetches GET /plans/{id}; renders:
   - Header (ticker, horizon, conviction badge, capital, generated_at)
   - Thesis section (markdown render)
   - Entry / Sizing / Stop block (table-style, prominent)
   - Exits, Catalysts, Risk flags
   - Citations list with external links
   - Price + indicator chart (use chart lib from decisions doc); fetch OHLCV from a dedicated GET /prices endpoint if needed — coordinate with M6 owner, or add a thin route here if missing
   - Notes section (list + add form)
   - Export buttons: download .md, download .json, print (CSS @media print + library if doc says so)
2. apps/web/src/lib/plan-to-markdown.ts — pure function Plan → markdown string.
3. apps/web/src/components/plan/ — section components (Thesis, EntryStop, Exits, etc.).

Acceptance: open /plans/{id} for a real plan, all sections render, markdown export downloads a clean file, print-to-PDF works in Chrome.

Files you may touch: apps/web/app/plans/, src/lib/plan-to-markdown.ts, src/components/plan/.
Files you MUST NOT touch: apps/web/app/page.tsx, app/watchlist/, app/settings/, apps/api/.

When done, push and summarize the section components + export flows.
```

---

## M8c — Watchlist + settings

**Where to run:** `git worktree add ../stockit-m8c -b feat/m8c-watchlist-settings`, parallel with M8a/b.

```
You are implementing milestone M8c (Watchlist + settings) of the StockIt project.

Context: ROADMAP.md, docs/frontend-stack-decisions.md, apps/web/src/types/generated.ts.
Pre-conditions: M6, M7, frontend decisions doc merged.

Deliverables:
1. apps/web/app/watchlist/page.tsx:
   - Lists watchlist items via GET /watchlist
   - Each row: ticker, last_refreshed_at, last plan link, "changed since last view" badge if last PlanRevision.created_at > user's last visit (track via localStorage)
   - Add row form (ticker)
   - Per-row "Refresh now" button → POST /watchlist/{id}/refresh
2. apps/web/app/settings/page.tsx:
   - Form for UserRiskConfig: risk_per_trade_pct, max_position_pct, preferred_llm (select: claude/openai/gemini)
   - PATCH endpoint (coordinate with M6 owner if not present)
3. Navigation: top nav linking Home / Watchlist / Settings / Logout, visible on every page.

Acceptance: add a ticker → see it in the list → refresh it → badge appears next visit; change risk config → next plan uses the new value.

Files you may touch: apps/web/app/watchlist/, app/settings/, src/components/nav/.
Files you MUST NOT touch: apps/web/app/page.tsx, app/plans/, apps/api/ (except a tiny PATCH /settings route if missing — coordinate).

When done, push and summarize the page layouts.
```

---

## M9 — Watchlist scheduler

**Where to run:** `git worktree add ../stockit-m9 -b feat/m9-scheduler`, after M6 merged. Parallel with M8.

```
You are implementing milestone M9 (Watchlist scheduler) of the StockIt project.

Context: ROADMAP.md, apps/api/app/pipeline/orchestrator.py, apps/api/app/models.py.
Pre-conditions: M6 merged.

Deliverables:
1. apps/api/app/scheduler.py:
   - APScheduler AsyncIOScheduler started in FastAPI lifespan
   - Daily job at 22:00 UTC: for each WatchlistItem, refetch data (force cache refresh), run a synth-only refresh against cached/refreshed analyst outputs (or re-run analysts if older than 24h), compute a diff vs the last Plan (changed thesis bullets, new catalysts, stop violation alerts), write a PlanRevision row with diff_json.
2. apps/api/app/pipeline/diff.py — `def diff_plans(old: Plan, new: Plan) -> dict` returning structured diff.
3. apps/api/app/routes/watchlist.py — ensure POST /watchlist/{id}/refresh shares the same code path (invoke the job for a single ticker on demand).
4. apps/api/tests/test_scheduler.py + test_diff.py.

Acceptance: tests pass; manual: add AAPL to watchlist, trigger refresh, see a PlanRevision row with sensible diff_json.

Files you may touch: apps/api/app/scheduler.py, app/pipeline/diff.py, apps/api/tests/. Minor edits to app/main.py for lifespan and app/routes/watchlist.py to share code.
Files you MUST NOT touch: analyst modules, data fetchers, llm/, synth.py, risk.py, schema.py.

When done, push and summarize the diff structure + job schedule.
```

---

## M10 — End-to-end verification

**Where to run:** `git worktree add ../stockit-m10 -b feat/m10-e2e`, after M6–M9 merged.

```
You are implementing milestone M10 (E2E verification) of the StockIt project.

Context: /Users/taladar/.claude/plans/i-have-an-idea-glimmering-puddle.md (Verification plan section has the 9 steps), ROADMAP.md.
Pre-conditions: M6, M7, M8, M9 all merged on main.

Deliverables:
1. apps/api/tests/test_e2e_pipeline.py — orchestrator-level test for the AAPL/swing happy path with real LLM (gated behind `--run-llm` pytest flag so it doesn't run in CI by default).
2. apps/web/tests/e2e/*.spec.ts — Playwright tests for: login flow, submit form → see plan, add to watchlist → refresh → see badge.
3. Execute manually the 9 verification steps from the plan and document the results in /Users/taladar/Documents/StockIt/docs/v1-acceptance.md (pass/fail for each, fixes applied).

Acceptance: all 9 steps pass; documented in v1-acceptance.md.

Files you may touch: tests/, docs/v1-acceptance.md, plus bug fixes anywhere needed (those must be small + scoped — escalate large breakages to me before fixing).
Files you MUST NOT touch: don't refactor anything outside fixing actual bugs.

When done, push and summarize: pass/fail of each step, any bugs found and fixed.
```

---

## M11 — Deploy

**Where to run:** `git worktree add ../stockit-m11 -b chore/m11-deploy`, after M10 merged. Requires YOU to create accounts and paste secrets.

```
You are implementing milestone M11 (Deploy) of the StockIt project.

Context: ROADMAP.md (M11 section).
Pre-conditions: M10 merged.

Deliverables:
1. Vercel config for apps/web:
   - vercel.json or project setup notes in docs/deploy.md
   - Required env vars listed (AUTH_SECRET, RESEND_API_KEY, ALLOWED_EMAILS, EMAIL_FROM, NEXT_PUBLIC_API_URL)
2. Fly.io config for apps/api:
   - fly.toml
   - Dockerfile (multi-stage Python 3.12, uv-based)
   - Release command runs `alembic upgrade head`
   - Required env vars listed (DATABASE_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, NEWSAPI_KEY, FRED_KEY, ALPHAVANTAGE_KEY, AUTH_SECRET, ALLOWED_EMAILS)
3. docs/deploy.md — step-by-step: create Neon/Supabase Postgres, create Fly app, create Vercel project, paste env vars, deploy in order (api first, then web).
4. Smoke test script docs/post-deploy-smoke.md — what to click after first deploy.

Acceptance: I follow docs/deploy.md and end up with a working production URL within 30 minutes; smoke test passes.

Files you may touch: vercel.json, fly.toml, Dockerfile, docs/.
Files you MUST NOT touch: application code (deploy work shouldn't require code changes — if it does, raise it with me first).

I (the user) handle: creating the Vercel/Fly/Neon accounts, generating real API keys, pasting them into the platform UIs.

When done, push and give me the exact ordered checklist I need to execute.
```
