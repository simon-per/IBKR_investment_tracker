# Working state

**Last updated: 2026-07-31**

`CLAUDE.md` is the durable guide — architecture, invariants, and the rules that were each a bug
first. **This file is the perishable half**: where the work actually stands, what is known-broken,
and what is worth doing next. Read both before you start; **leave this one accurate before you stop**
— CLAUDE.md's *Keeping STATUS.md current* says exactly when and what.

Rules for keeping it useful: **delete entries once they stop being true** rather than accumulating
history, and **describe figures rather than publishing them** (the repo is public, the base currency
is user-switchable, and a pasted total goes stale silently — check the API or the DB instead).
*Recent sessions* at the bottom is the single exception to the first rule, and it is capped at five.

---

## Needs a human

- **Nothing from 2026-07-31 has been pushed.** Eight commits sit on local `main` (see *Shipped
  locally* below). Pushing auto-deploys within 10 minutes, so land it **outside** a Berlin sync slot
  (08/13/15/20/22:00) — item 2 below removes that constraint but is not installed yet.
- **Turn on the write API auth.** `app/auth.py` gates every `POST/PUT/PATCH/DELETE` under `/api/`,
  but it is **inert until `API_ADMIN_TOKEN` is set** — deliberately, so shipping it could not 401 the
  running site. Until then `/api/` is what it has always been: anyone who can reach the host can
  change the base currency, edit the watchlist and start syncs that spend the IBKR and Yahoo budgets.
  Generate a token (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), put it in
  `/root/IBKR_investment_tracker/backend/.env`, and paste the same value into the app's lock button
  (header, beside Sync). The footer shows *write API unauthenticated* while it is off.
- **Rotate the IBKR Flex token.** It travelled as a `t=` URL parameter into `sync_runs.message` and
  was served by the public `/api/scheduler/history` until the 2026-07-28 scrub. `app/redact.py` now
  redacts on write *and* on read, so it cannot recur — but redaction cannot un-leak what was already
  reachable. Only Simon can rotate it (IBKR portal → Reports → Settings → Flex Web Service).
- **Backfill the 2025 tax year.** A YTD Flex Query cannot reach it, so 2025 correctly reports
  `dividend_source='yfinance_estimate'`. Needs a one-off period change on the query (or a browser
  download ingested via `app/cli/ingest_flex_xml.py`), then set it back to YTD. Ingestion is
  idempotent, so this is safe to repeat. The UI no longer hardcodes 2024 as the earliest tax year —
  both it and the chart's ALL range read `min(taxlots.open_date)` — so the backfilled year appears
  on its own once ingested.

## Watching

- **IBKR `1001` on the retry slots.** Four consecutive failures on 2026-07-29 (11:00 and 18:00 UTC
  among them). This is documented flaky behaviour, not a regression: `1001` at the *request* step is
  fatal-fast on purpose, and the schedule is designed so a later slot recovers. The **08:00
  `full_sync` is the dependable slot** — if that one also starts failing, use the offline XML path
  rather than retrying, which is what caused three token lockouts historically.
- **MCO and MRVL each forecast off only 2 samples.** Surfaced by the new `forecast_samples` field the
  day it shipped, and badged `n=2` in the dividends table. Not known-wrong — both are real payers with
  plausible schedules — but two samples is the exact shape that let SBI project a fake monthly cadence,
  so those projections deserve one look before being trusted. Check `manage_mappings list` for a
  `DIVIDENDS PREDATE MAPPING` flag (which would mean the rows came from an older ticker) rather than
  assuming either way.
- **`market_prices` gaps heal only at 08:00.** The 7-day jobs restore current value after a split
  purge; the full history comes back at the next 730-day `full_sync`.

## Known rough edges (accepted, not bugs)

- **The Dividends KPI strip does not follow the year filter.** Its labels are absolute ("2026 so
  far", "Last 12 months") and the growth block is unwindowed by design — so selecting 2027 still
  shows this year's figures. Pinned by `test_growth_is_identical_whichever_year_is_selected`. This
  is the most likely thing to read as a bug when it isn't.
- **"Next 12 months" stays visible with the Forecast toggle off**, because that card is inherently a
  projection and hiding it would collapse the four-up grid. The per-year panel *does* respect the
  toggle, since it is the one surface that mixes measured and projected into one bar.
- **The monthly chart's tick labels are cramped at 390 px** (twelve months, no room). Legible, not
  pretty.
- **Accumulating ETFs correctly show no dividends** — DBPG, EMIM, IWDA, SXR8, VWCE, XAIX, XNAS.
  Verified, not assumed. **Don't "fix" their absence.**
- **Activity's Market Value delta and the chart's "Value change" are the same number**, shown twice
  on purpose: the card answers "how much did the portfolio move" at a glance, the chart header pairs
  it with Period Gain so the difference between the two is visible. Neither is a return.
- **`/api/portfolio/activity` shows dividends net and estimates unqualified-but-badged.** A
  `yfinance_estimate` row is a gross guess with no withholding and reads *Dividend · est.*; the era
  splice that governs the Dividends tab does **not** apply here, because a ledger's job is to show
  what is on record rather than to pick a source per period.

## Shipped locally 2026-07-31 — NOT deployed

Eight commits on local `main`, none pushed. Suites: backend 357 → 425, frontend 45 → 85, `tsc -b`
and `npm run build` clean. Verified against a live uvicorn as well as through the test client —
`/health`, the activity ledger and its CSV, the 400s on a bad `kind` and an over-wide window, write
auth in all four states, the 429 with `Retry-After`, and a persistent-job-store restart preserving
run times. What is **not** verified is the ledger against real trades and cash flows: the checked-in
`portfolio.db` predates both, so only dividends came back locally. Unit tests cover those shapes; a
prod snapshot would confirm them.

What landed, and why each was worth doing:

- **`_ttm_growth_from_quarterly` was duplicated and divergent**, so one security could report
  different earnings growth on `/api/fundamentals/portfolio` than on `/api/watchlist`. Now
  `app/services/ttm_growth.py`, with the 5–7-quarter tier the fundamentals copy lacked.
- **Every chart date boundary went through `toISOString()` on a local date**, so YTD/MTD started a
  day early in any positive-UTC-offset zone. `lib/dateRanges.ts` is local-calendar throughout.
- **Inception is read from the data**, not hardcoded twice (`2024-05-28` for ALL, `2024` for the tax
  year picker) — see *Needs a human*.
- **Four cards and every sortable column in Fundamentals/Watchlist were mouse-only**, and the tab
  strip had no ARIA at all. Shared `CollapsibleCardHeader` / `SortableTh`, full WAI-ARIA tabs, and
  21 jsdom tests pinning it.
- **Four more surfaces let a backend failure read as empty data.** That class is now closed.
- **The write API had no authorization anywhere** — off by default, see *Needs a human*. Alongside:
  a per-IP rate limit, `X-Request-ID` on every response with a redacting 500 handler, and `/health`
  reporting version/commit/scheduler/auth, rendered in a new footer.
- **An Activity tab.** `trades`, `corporate_actions`, `cash_flows` and `dividend_payments` were all
  ingested and depended on with no read surface at all. Cash rows carry `counts_as_money_in`, so the
  transfer audit CLAUDE.md prescribes is a UI action rather than an ssh command.
- **A deploy landing in a Berlin slot no longer loses that sync** — persistent APScheduler job store,
  which is *Worth doing next* item 9 from yesterday.

## Watch after the first deploy

- **The scheduler job store is new.** `backend/scheduler_jobs.db` is created on first start and
  bind-mounted; `deploy.sh` touches it so Docker cannot make it a directory. Confirm
  `/api/scheduler/status` still lists five jobs after the deploy, and that the container logs show
  `kept, next run:` on the *second* restart rather than recomputing.
- **The CSP is new.** It is strict on `script-src` and the bundle is entirely self-hosted, so nothing
  should break — but a blocked resource shows up only in the browser console, not in any log we keep.
- **`index.html` is now `no-cache`.** Deploys should take effect on reload without a hard refresh.

## Worth doing next

Rough priority. Item 1 is written but not installed; the rest are not started.

1. **Install the guarded auto-deploy script — WRITTEN, NOT INSTALLED.** `ops/auto-deploy.sh` is in
   the repo (it previously existed only as `/root/auto-deploy.sh`, unversioned and unreviewed despite
   governing every deploy) and adds the sync-slot guard: it refuses to deploy within 10 minutes
   either side of a Berlin slot and defers to the next tick. The boundary logic is tested across all
   five slots, the quiet hours and the midnight wrap. **The VPS still runs the old copy** —
   installing it changes deploy behaviour, so it needs a deliberate step:

       scp ops/auto-deploy.sh root@<host>:/tmp/ && ssh root@<host> 'install -m 755 /tmp/auto-deploy.sh /root/auto-deploy.sh'

   Verify afterwards by watching `/root/auto-deploy.log` for a `SKIP: within 10min` line near a slot.
   The persistent job store now recovers a missed slot within 30 minutes anyway, so this is belt to
   that braces rather than the only defence.
2. **Verify the Activity ledger against real trades and cash flows.** Only its dividend rows were
   seen live: the checked-in `portfolio.db` predates the other three tables. In particular confirm
   the 22 in-kind transfer rows render as *Transfer · not money in*, since that badge is the audit
   CLAUDE.md prescribes before trusting any money-added figure.
3. **Commit the visual-regression harness.** The Playwright screenshot loop that verified the
   Dividends tab lives *outside* the repo, so it is not reproducible from a clean checkout. It cannot
   simply become a `frontend` devDependency: `deploy.sh` runs `npm ci` on a `--no-cache` rebuild and
   Playwright's postinstall pulls ~150 MB of Chromium, which would tax every 10-minute deploy. Needs
   a separate package or a skipped-download flag. (`@testing-library/react` + `jsdom` *did* go in on
   2026-07-31 — a few MB, which is affordable; Playwright is the one that is not.)
4. **The bundle is 877 kB / 260 kB gzipped in one chunk**, and Vite warns on every build. Recharts is
   most of it and only three tabs use it, so a `React.lazy` split per tab is the obvious first cut.
   Not urgent on a desktop-first single-user app, but it is the largest remaining rough edge.
5. **`/api/dividends/summary` still has no `response_model`.** Nothing but `tests/test_api_smoke.py`
   stops a field rename silently blanking the Performance tab's provenance footnote.
6. **Fold `PRE_OWNERSHIP_HISTORY_YEARS` pruning into a scheduled job.** `prune_empty_dividends.py`
   is a manual CLI; the ingest window now prevents new junk, so this is cleanup-only and low value.

Also noted, not yet items: `CLAUDE.md` says React 18; `package.json` pins `react@^19.2.0`. And
`CLAUDE.md`'s test counts (357 backend + 45 frontend) are now 425 + 85.

## Local development traps

Each of these cost real time at least once.

- **`SCHEDULER_ENABLED=false` in `backend/.env` for any local run.** Otherwise starting uvicorn arms
  the five daily Europe/Berlin jobs against the live Flex token and Yahoo. Defaults to `True` so
  production is unaffected.
- **Check which port Vite actually took.** If 5173 is occupied it moves to 5174 and says so once. A
  stray dev server on 5173 configured against production means you are reading prod data and issuing
  requests to the live site — including `/api/dividends/summary`, which can enqueue a Yahoo sync.
- **Use a snapshot of the production DB, not the checked-in `portfolio.db`** — the latter predates
  trades, cash flows and the IBKR dividend era, so it exercises none of the interesting shapes.
  `sqlite3 .backup` on the VPS, copy down, point `DATABASE_URL` at it, **delete it afterwards** (it
  is real account data; `*.db` is gitignored but it should not linger).
- **The base currency is whatever the user last picked** (`/api/settings`, EUR/CHF/USD). Every money
  figure moves with it, so never compare a number across sessions without checking it.
- **Don't push within ~10 minutes of a Berlin sync slot** (08/13/15/20/22:00). Auto-deploy rebuilds
  in ~90 s, so an overlapping deploy used to lose that sync outright. The persistent job store now
  recovers it on startup if the gap is under 30 minutes — but a slow `--no-cache` rebuild can exceed
  that, so the habit still earns its keep.
- **`curl 127.0.0.1:<vite port>` fails while the browser works.** Vite binds `localhost`, which
  resolves to `::1` first on this machine, so the IPv4 literal gets connection-refused and looks like
  a dead dev server. Use `http://localhost:<port>`.
- **A test that starts a scheduler drops a `scheduler_jobs.db` wherever it runs.** `tests/conftest.py`
  blanks `scheduler_jobstore_url` for the whole suite, so an in-memory store is the default; a test
  that wants persistence points it at `tmp_path` itself.
- **`sqlite:////tmp/x.db` in Git Bash lands in `C:\tmp`, not the shell's `/tmp`.** The SQLAlchemy URL
  is read by Python, which does not apply the MSYS path translation, so a stray file goes somewhere
  `ls /tmp` will not show it.

## Recent sessions (last 5)

One line each, newest first. **Drop the oldest rather than growing this list** — `git log` holds the
detail; this exists so the next session knows what just moved without reading it. Distinct from the
*Shipped* section above, which is actionable (what to check on prod, and what has already been
confirmed) and gets deleted once nothing in it is outstanding: these lines are permanent, so don't
"tidy up" the overlap by deleting the wrong one.

- **2026-07-31** — enterprise-readiness pass, eight commits, **not pushed**: shared TTM growth,
  locale-independent chart dates, inception read from the data, keyboard/ARIA across the tab strip and
  every collapsible and sortable header, four more explicit error states, optional write auth +
  per-IP rate limit + request ids + `/health` build identity, the Activity ledger over the four
  unread tables, a persistent scheduler job store, delta-chip and scroll-affordance consolidation,
  real product chrome. Suites 357 → 425 backend, 45 → 85 frontend.
- **2026-07-30** — two batches: five audit fixes (Yahoo gating, `openDateTime` off ibflex, SELL beats
  the cost-conserved heuristic, tax-report honesty, dividend card net), then the SBI dividend bug —
  poisoned estimates purged on prod, mapping changes now retire the rows they produced, source-aware
  dividend key, provenance detector, batched price/lot writes, forecast/yield qualifiers. Suite
  313 → 357, deployed and verified. Lost the 08:00 full_sync to a deploy landing in the slot.
- **2026-07-29** — correctness sweep (16 fixes) plus dividend growth (MoM/YoY) and the DividendsTab
  rebuild; scheduler gated behind `SCHEDULER_ENABLED`; STATUS.md split out of CLAUDE.md.
- **2026-07-28** — external cash ledger live on prod (deposits ingested, transfers excluded) and the
  money-in splice; Dividends tab + breakdown endpoint; Flex token redacted from stored and served errors.
- **2026-07-27** — SBI mapping repair: reject a Yahoo ticker quoting a different currency than the
  security, second FX provider fallback for currencies the ECB set lacks, `manage_mappings` CLI for
  the last table still edited by hand. (Prices were purged here; the dividend rows were not — that
  half surfaced on 07-30.)
