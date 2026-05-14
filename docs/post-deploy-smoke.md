# Post-deploy smoke test

Run this against the live URLs after the first deploy (and after any
release-day deploy you don't fully trust). Should take ~10 minutes.

Substitute your real URLs:
- API: `https://stockit-api.fly.dev`
- Web: `https://stockit-web.vercel.app`

Each step lists what to do, what to expect, and what it would mean if it
failed. If anything fails, stop, fix it, then restart from the top — the
later steps assume the earlier ones passed.

---

## 1. API is up

```bash
curl https://stockit-api.fly.dev/health
```

**Expect:** `{"status":"ok"}` with HTTP 200.

**If fails:** `fly logs -a stockit-api`. Most likely the release command
(`alembic upgrade head`) failed — check the migration output. Other common
cause: `DATABASE_URL` missing the `+asyncpg` driver prefix.

---

## 2. Migrations applied

```bash
fly ssh console -a stockit-api -C "alembic current"
```

**Expect:** prints the latest revision id with `(head)` suffix.

**If fails:** migrations weren't applied. Run `fly ssh console -a stockit-api
-C "alembic upgrade head"` manually and read the error.

---

## 3. Auth allowlist (negative case)

Open the web URL in an **incognito** window. Enter an email **not** in
`ALLOWED_EMAILS`. Submit.

**Expect:** form shows "Check your email" anyway (Auth.js doesn't leak which
emails are allowed). The actual magic-link email is never sent. Check Resend
dashboard → Logs: there should be no send for that address.

**If it sends:** the `signIn` callback isn't enforcing the allowlist — verify
`ALLOWED_EMAILS` env var is set on Vercel (Production scope) and redeploy.

---

## 4. Auth allowlist (positive case)

Same window, enter your own email (must be in `ALLOWED_EMAILS`). Submit.
Check your inbox.

**Expect:** magic-link email arrives within ~30 seconds from
`AUTH_EMAIL_FROM`. Click it. Lands on `/` showing the plan input form and
your email in the top nav.

**If no email:** Resend dashboard → Logs. Common causes: sender not verified,
`AUTH_RESEND_KEY` typo, sender domain DNS not propagated.

---

## 5. Generate a plan (AAPL, $10,000, swing)

On `/`, fill in:
- Ticker: `AAPL`
- Capital: `10000`
- Horizon: `swing`
- Risk %: leave at default

Submit.

**Expect:** redirected to `/plans/<id>`. The plan renders within ~90s with:
- four analyst sections (fundamentals, technicals, news, macro),
- an entry price, stop price, and at least one exit level,
- sizing (shares + dollar risk) that matches `capital × risk_pct` within 1 share,
- stop price **strictly below** entry,
- citations with clickable URLs on at least one analyst section.

**If it 500s:** open Fly logs (`fly logs -a stockit-api`) and look for the
traceback. Most common: missing one of the LLM keys, missing data-API key,
or a CORS error (which would show in the browser console, not Fly logs).

**If it 401s in the browser:** `AUTH_SECRET` on Vercel and `AUTH_SECRET` on
Fly don't match. They must be byte-identical.

**If CORS error in browser console:** `WEB_CORS_ORIGINS` on Fly doesn't
include the Vercel URL exactly (no trailing slash, scheme must match).

---

## 6. Plan persistence

Refresh the `/plans/<id>` page.

**Expect:** plan renders identically — it was saved in Postgres, not just in
memory.

**If 404:** the synth happened but the persist step failed. Check Fly logs;
likely a DB schema mismatch (alembic not at head) or a Pydantic validation
error in `app/routes/plans.py`.

---

## 7. Markdown / PDF export

On the plan page, click **Export Markdown** and **Print to PDF**.

**Expect:** Markdown downloads with the same content as on screen. Print
dialog opens with a clean print stylesheet (no navbar/footer).

---

## 8. Watchlist add + manual refresh

Go to `/watchlist`. Add `AAPL` (or whatever ticker you used in step 5).

**Expect:** row appears with the latest plan id linked. Click **Refresh** on
the row.

**Expect:** within ~60s, the row updates with a new revision badge ("rev 2")
and the plan-link target changes if the new revision is materially different.

**If refresh hangs:** scheduler/refresh worker is wedged. `fly logs -a
stockit-api` should show the orchestrator running. The most common cause is
LLM rate-limit; check provider dashboards.

---

## 9. Settings → risk config

Go to `/settings`. Change risk % to `0.5`. Save.

Go back to `/`, generate a new plan for any ticker.

**Expect:** sizing now uses the new risk %; dollar risk on the rendered plan
≈ `capital × 0.005`.

**If save fails:** check that the API's `/settings` PUT endpoint is reachable
— browser network tab will show the request URL. If it's hitting the Vercel
domain instead of the Fly domain, `NEXT_PUBLIC_API_URL` is wrong on Vercel.

---

## 10. Scheduled refresh (overnight check)

Leave the watchlist row in place. Come back the next day after 22:00 UTC.

**Expect:** the row's revision incremented overnight. Fly logs near 22:00
UTC show one line per watchlist item from the APScheduler job.

**If no overnight refresh:** check `STOCKIT_SCHEDULER_ENABLED=1` in
`fly.toml` (or as a secret), and confirm the Fly machine stayed running
(`fly status -a stockit-api`). If `auto_stop_machines` got flipped to `true`
somewhere, the scheduler dies with the machine.

---

## Pass criteria

Steps 1–9 all pass within one sitting → the deploy is live.
Step 10 confirms the daily scheduler the next morning.

If anything's flaky, jot it in the PR description for M11 before signing off.
