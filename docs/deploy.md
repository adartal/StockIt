# Deploy StockIt to production

Step-by-step. Follow top to bottom. Target: working production URL in ~30 minutes
after accounts exist.

Two services + one database:
- **Postgres** on Neon (free tier is fine) — or Supabase if you prefer.
- **API** (`apps/api`) on Fly.io.
- **Web** (`apps/web`) on Vercel.

Deploy order is **DB → API → Web**. The web app needs the API URL; the API needs
the database URL.

---

## 0. Prerequisites

Local CLIs:

```bash
# Fly
brew install flyctl
fly auth login

# Vercel
pnpm add -g vercel
vercel login

# Neon (optional — you can do everything from the dashboard)
brew install neonctl
neon auth
```

Repo state:

- Branch `chore/m11-deploy` merged to `main` (or deploying directly from the
  branch — both work; Vercel/Fly only care about which commit).

---

## 1. Postgres (Neon)

1. Go to <https://console.neon.tech> → **New Project**.
2. Region: pick the same region you'll use for Fly (`iad` = AWS us-east-1).
3. Postgres version: 16 (default is fine).
4. After creation, open the project → **Dashboard** → **Connection string**.
   Copy the **pooled** connection string. It looks like:
   ```
   postgresql://USER:PASS@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
5. Convert the scheme for asyncpg by replacing `postgresql://` with
   `postgresql+asyncpg://`. Drop the `?sslmode=require` query — asyncpg uses
   `ssl=true` differently. The final form for `DATABASE_URL`:
   ```
   postgresql+asyncpg://USER:PASS@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb
   ```
   (Alembic reads the same env var and tolerates either driver prefix.)

Save this somewhere — you'll paste it into Fly in step 2.

> **Supabase alternative:** create a project, copy the connection string from
> Settings → Database → Connection string → URI. Same `postgresql+asyncpg://`
> rewrite applies. Use the connection pooler URI (port 6543) for the app and
> the direct URI (port 5432) for one-off `alembic` runs if you ever need them.

---

## 2. API (Fly.io)

From the repo root in the `chore/m11-deploy` worktree:

```bash
cd apps/api
fly launch --no-deploy --copy-config --name stockit-api --region iad
```

`fly launch` will detect the existing `fly.toml` and `Dockerfile`. Answer
**no** to "would you like to set up a Postgres database" (we have Neon) and
**no** to Redis.

If `fly launch` rewrites `fly.toml` in a way you don't want, copy this repo's
`apps/api/fly.toml` back over it before deploying. The shipped config:
- runs `alembic upgrade head` as the release command,
- keeps one machine always running (scheduler depends on it),
- exposes `/health` for Fly's load-balancer checks.

Set secrets (real values come from you — Claude can't see them):

```bash
fly secrets set \
  DATABASE_URL='postgresql+asyncpg://...neon...' \
  ANTHROPIC_API_KEY='sk-ant-...' \
  OPENAI_API_KEY='sk-...' \
  GEMINI_API_KEY='...' \
  NEWSAPI_API_KEY='...' \
  FRED_API_KEY='...' \
  ALPHA_VANTAGE_API_KEY='...' \
  AUTH_SECRET='<openssl rand -hex 32>' \
  ALLOWED_EMAILS='you@example.com,partner@example.com'
```

(Names match what the code reads: see `apps/api/.env.example`. `AUTH_SECRET`
must be byte-identical to the Vercel `AUTH_SECRET` set in step 3 — same
HMAC key signs and verifies the session JWT in both processes.)

Deploy:

```bash
fly deploy
```

The release command runs `alembic upgrade head` against Neon before the new
machine takes traffic. Watch the logs — if migration fails, the new release
is aborted and the previous machine keeps serving.

Verify:

```bash
curl https://stockit-api.fly.dev/health
# → {"status":"ok"}
```

Note the URL — it's what Vercel needs as `NEXT_PUBLIC_API_URL`.

---

## 3. Web (Vercel)

From the repo root:

```bash
cd apps/web
vercel link
```

Answer the prompts:
- Set up and deploy? **Y**
- Scope: your team.
- Link to existing project? **N**
- Project name: `stockit-web` (or whatever).
- In which directory is your code? **.** (you're already in `apps/web`).
- Override settings? **N** (the `vercel.json` in this directory tells Vercel
  it's a Next.js project using pnpm).

After link, set env vars. Either via dashboard
(Project → Settings → Environment Variables) or CLI:

```bash
vercel env add NEXT_PUBLIC_API_URL production
# paste: https://stockit-api.fly.dev

vercel env add AUTH_SECRET production
# paste: same value you used for AUTH_SECRET on Fly

vercel env add AUTH_RESEND_KEY production
# paste: re_...  (from resend.com → API Keys)

vercel env add AUTH_EMAIL_FROM production
# paste: "StockIt <noreply@yourdomain.com>"  (must be a verified Resend sender)

vercel env add ALLOWED_EMAILS production
# paste: same comma-separated list you used on Fly
```

> The Auth.js Resend provider in [apps/web/auth.ts](../apps/web/auth.ts)
> accepts either `AUTH_RESEND_KEY`/`RESEND_API_KEY` and
> `AUTH_EMAIL_FROM`/`EMAIL_FROM` — the `AUTH_*` form is preferred because
> Auth.js v5 auto-loads variables with that prefix.

Deploy:

```bash
vercel --prod
```

Vercel hands back a URL like `https://stockit-web.vercel.app`. Save it.

---

## 4. Tell the API about the Web URL (CORS)

```bash
cd ../api
fly secrets set WEB_CORS_ORIGINS='https://stockit-web.vercel.app'
```

Fly will roll a new machine with the updated CORS allowlist. Without this,
the browser will block API calls from the Vercel domain.

---

## 5. Smoke test

Run [docs/post-deploy-smoke.md](./post-deploy-smoke.md). Should take ~10
minutes and exercises the same flow as the M10 acceptance tests against the
real deployed stack.

---

## Environment variable reference

### Fly (`apps/api`)

| Name | Where it's read | Purpose |
|---|---|---|
| `DATABASE_URL` | `app/db.py` | asyncpg Postgres URL (Neon pooled). |
| `ANTHROPIC_API_KEY` | `app/llm/claude.py` | Primary LLM. |
| `OPENAI_API_KEY` | `app/llm/openai.py` | Fallback LLM. |
| `GEMINI_API_KEY` | `app/llm/gemini.py` | Fallback LLM. |
| `NEWSAPI_API_KEY` | `app/pipeline/data/news.py` | Newsroom feed. |
| `FRED_API_KEY` | `app/pipeline/data/macro.py` | Macro rates. |
| `ALPHA_VANTAGE_API_KEY` | `app/pipeline/data/prices.py` | Intraday fallback for yfinance. |
| `AUTH_SECRET` | `app/auth.py` | HMAC key — must equal the Vercel `AUTH_SECRET`. |
| `ALLOWED_EMAILS` | `app/auth.py` | Comma-separated allowlist. |
| `WEB_CORS_ORIGINS` | `app/main.py` | Comma-separated origin allowlist for CORS. |
| `STOCKIT_SCHEDULER_ENABLED` | `app/scheduler.py` | Set in `fly.toml`; leave `1`. |

### Vercel (`apps/web`)

| Name | Where it's read | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | client + server, e.g. `app/api-client.ts` | Base URL of the Fly API. |
| `AUTH_SECRET` | `auth.ts` (Auth.js v5) | HMAC key — must equal Fly `AUTH_SECRET`. |
| `AUTH_RESEND_KEY` (or `RESEND_API_KEY`) | `auth.ts` | Resend API key for magic-link email. |
| `AUTH_EMAIL_FROM` (or `EMAIL_FROM`) | `auth.ts` | Sender, must be a verified Resend identity. |
| `ALLOWED_EMAILS` | `auth.ts` `signIn` callback | Same allowlist as the API. |

---

## Rollback

- **Web:** Vercel → Deployments → previous → "Promote to Production".
- **API:** `fly releases list` then `fly releases rollback <version>`.
- **DB:** Neon has point-in-time restore in the dashboard. Don't roll back
  the app to a release whose migrations have been applied without first
  restoring the DB — alembic is forward-only by default.

---

## Costs (rough, as of 2026-05)

- Neon free tier: 0.5 GB storage, fine until ~tens of thousands of plans.
- Fly: ~$3–5/mo for one `shared-cpu-1x` 1 GB machine kept warm.
- Vercel hobby: free.

Total expected: under $10/month plus whatever the LLM and data APIs cost.
