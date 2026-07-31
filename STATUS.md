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

- **Nothing from 2026-07-31 has been pushed** — `git push` is **refused to an agent by the permission
  classifier**, so this is a human step, not an oversight. The unpushed work sits on local `main` (see
  *Shipped locally* below; `git log --oneline origin/main..main` is the current list — the count is
  deliberately not written here, it drifted three times in one session). The tree is clean and both
  suites are green, so it is one command:

      git push origin main

  **Or run `bash ops/finish-deploy.sh`**, which does all three *Needs a human* deploy steps in the
  only safe order and refuses to reach step 2 until `/health` reports the commit it just pushed.
  It also checks the Berlin clock before pushing — via Python's `zoneinfo`, because **Git Bash on
  Windows silently ignores `TZ=`** and returns UTC, which in summer would put the guard two hours
  out in the unsafe direction and wave a push straight into the 08:00 slot. Every step asks first
  and can be skipped.

  Pushing auto-deploys within 10 minutes, so land it **outside** a Berlin sync slot
  (08/13/15/20/22:00). The new persistent job store recovers a slot missed by under 30 min once it is
  live — but it is not live until this deploy lands, so **this first one still has to be timed by
  hand**; afterwards the timing stops mattering. *Worth doing next* item 1 would prevent the overlap
  outright. Confirm it landed from the browser: the footer reports the running commit.
- **Turn on the write API auth.** `app/auth.py` gates every `POST/PUT/PATCH/DELETE` under `/api/`,
  but it is **inert until `API_ADMIN_TOKEN` is set** — deliberately, so shipping it could not 401 the
  running site. Until then `/api/` is what it has always been: anyone who can reach the host can
  change the base currency, edit the watchlist and start syncs that spend the IBKR and Yahoo budgets.
  Generate a token (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), put it in
  `/root/IBKR_investment_tracker/backend/.env`, and paste the same value into the app's lock button
  (header, beside Sync). The footer shows *write API unauthenticated* while it is off. **Do it after
  the deploy, not before** — the currently-live frontend has no lock button, so enabling auth first
  would refuse its sync and currency controls with no way to unlock them.

  This and *Worth doing next* item 1 are both **production config edits on the VPS, which the
  permission classifier refuses to an agent** — correctly. Everything either needs is written and
  tested; only the two commands remain.
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

Nothing pushed (`git log --oneline origin/main..main`). Suites: backend 357 → 451, frontend 45 → 91,
`tsc -b` and `npm run build` clean.

**The bundle is now code-split**, which changed the shape of a deploy for users. It was one 891 kB /
264 kB-gzipped chunk; it is now four eager files (app 52 kB gz, react 57, charts 119, query 15) plus
one per deferred tab. Two separate wins: the seven non-default tabs no longer load at first paint,
and — the bigger one, given the VPS redeploys within 10 minutes of any push — **the chunk that
re-hashes on every deploy fell from 264 kB gzipped to 52 kB**, because vendor code now sits in files
that only change when a dependency does. nginx already serves `/assets/` `immutable` for a year, so
that caching is real rather than theoretical. Recharts stays eager on purpose: three components on
the *default* Performance tab use it, so deferring it would only move the wait.

`ui/LazyTabPanel.tsx` exists because splitting introduced a failure the eager imports could not
have. Chunks are content-hashed and the VPS redeploys constantly, so a browser holding the page
across a deploy requests a filename that no longer exists — unhandled, that rejection reaches the
app-level boundary in `App.tsx` and blanks the whole dashboard, which is strictly worse than before
the split. The panel-scoped boundary recognises the wording Vite/webpack/Safari each use for it,
says a new version shipped, and offers the reload that fixes it (`index.html` is `no-cache`, so a
reload genuinely resolves it). A non-chunk error still shows its real message — mislabelling a
genuine bug as a deploy race would have users reloading forever.

Verified in a real browser against the built output under the production CSP, since chunk boundaries
are a property of the build that no unit test can observe: 4 chunks at first paint, none of the
seven deferred ones; each tab fetching its own chunk on click, all 200; every panel mounting; zero
CSP violations.

**Verified against a production DB snapshot and in a real browser** (Playwright — now committed as
`e2e/`), not just through the test client. That is worth stating because it found three defects the whole green
suite did not:

- **Trades were converted wrong.** `trades.proceeds`, `trades.realized_pnl` and
  `corporate_actions.proceeds` are stored in the trade's **own** currency — there is no `_eur` column
  on either, unlike `cash_flows.amount_eur` and `dividend_payments.*_eur`. The ledger applied only
  the EUR→base factor, so a CAD 30.27 realized gain read as CHF 27.85 instead of CHF 17.15 and the
  ledger's realized total sat 6.8% away from `/api/portfolio/summary`. Both now agree to the cent.
- **67 BUY rows showed `CHF 0.00` realized.** IBKR sends `fifoPnlRealized=0` on every buy; rendering
  it asserts a realized result where there is none.
- **Fractional share counts rounded to `0`** (and a fractional sell to `-0`). This account trades
  0.5 SOXQ, 0.3 MU, 0.1 CSU routinely, so it was most rows, not an edge case.

Confirmed on the snapshot: 194 events in the default window; **22 in-kind transfer rows badged
*Transfer · not money in*** and 26 deposits + 1 withdrawal counted, matching the DB exactly; the
ledger's deposit total equals `/api/portfolio/contributions`'s `deposits_eur` to the cent (two
independent code paths). All eight tabs render with zero console errors. With the backend stopped,
eleven surfaces report the failure explicitly and none falls back to an empty-data message.
Keyboard: arrow/Home/End across the tab strip, Enter on all four collapsible headers, 9 headers
carrying `aria-sort`.

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
- **`prune_empty_dividends` was deleting the forecast's cadence basis.** Found while assessing
  whether to automate it — the answer turned out to be "fix it first". The CLI deleted any computed
  row carrying no income, on the stated grounds that it "deletes only rows the readers already
  ignore". That stopped being true when the forecast was changed to infer cadence from the **raw**
  history: a pre-ownership yfinance row is income-free *and* load-bearing, and dropping it is what
  the "only 15 of 36 payers project" bug looked like. Running the documented cleanup would have
  quietly reverted that fix for every recently-bought payer. Prune is now bounded by the ingest
  window it should always have mirrored — a row goes only if it is older than the history
  `sync_dividend_data` deliberately retains — and a security with no lots is left alone entirely,
  matching ingest's own refusal to guess a cutoff. The existing test fixture had masked it by
  holding 10 shares with no tax lot, which cannot happen in real data.
- **The browser checks are in the repo** as `e2e/`, a package deliberately separate from `frontend/`:
  `deploy.sh` runs `npm ci` inside `frontend/` on every `--no-cache` rebuild and Playwright's
  postinstall pulls ~150 MB of Chromium, which would tax a deploy that runs every 10 minutes. Nothing
  in the deploy path touches `e2e/`. Six scripts with a table of preconditions in its README —
  `a11y` (14 checks), `sweep` (16), `csp` (4), `chunks` (33), plus `errors` (backend deliberately
  down) and `ledger` (needs a prod snapshot). Screenshots are gitignored: real account data, public
  repo.

  Committing them surfaced one flaw. **`csp.mjs` used to run against the dev server, where it could
  not have been meaningful:** Vite injects an inline `<script type="module">` for react-refresh and
  `script-src 'self'` blocks it, so the app never boots and the script reports a violation that
  cannot exist in production. It now targets `vite preview`. The *conclusion* was never wrong — the
  CSP had already been verified against the real build (see *Watch after the first deploy*), and
  re-running it there passes 4/4 — but the reusable script was measuring Vite's HMR transport.

## Watch after the first deploy

- **The scheduler job store is new.** `backend/scheduler_jobs.db` is created on first start and
  bind-mounted; `deploy.sh` touches it so Docker cannot make it a directory. Confirm
  `/api/scheduler/status` still lists five jobs after the deploy, and that the container logs show
  `kept, next run:` on the *second* restart rather than recomputing.
- ~~The CSP~~ — **verified, nothing to watch.** The production policy was applied to the real
  `npm run build` output in a browser: eight tabs render, the recharts SVGs and lucide icons draw,
  the `data:` favicon loads, and the console reports zero violations. Worth having done rather than
  waiting, since a blocked resource shows up only in the browser console and in no log we keep.
- **`index.html` is now `no-cache`.** Deploys should take effect on reload without a hard refresh.

## Worth doing next

Rough priority. Item 1 is written but not installed; item 2 is not started.

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
2. **Fold `PRE_OWNERSHIP_HISTORY_YEARS` pruning into a scheduled job — reassess before building.**
   `prune_empty_dividends.py` is a manual CLI and the ingest window already prevents new junk, so
   there is very little left for a scheduled run to find. Investigating this on 2026-07-31 turned up
   a **defect in the CLI rather than a case for automating it** (below), which is a fair warning
   about automating a deleter over financial rows: the value is small and the downside is silent.
   If it is built, it must reuse the CLI's predicate rather than re-deriving one.

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
- **`pkill` is not installed** (Git Bash has no procps). `pkill -f uvicorn` prints
  "command not found" and exits non-zero — easy to miss inside a `&&` chain — so the old server keeps
  the port and the new one dies on bind while `--strictPort`'s error scrolls past in a log file. The
  result is a dev server quietly answering from the *previous* config, which cost real time here: a
  browser pass appeared to show an empty ledger when it was reading the stale local DB. Kill by PID:
  `netstat -ano | grep ':8000 ' | grep LISTENING` then `taskkill //F //PID <pid>` (double slashes —
  MSYS eats single ones).
- **A dev server against a prod snapshot must run on port 5173.** `frontend/.env` points
  `VITE_API_URL` at `localhost:8000`, so the browser calls the backend cross-origin and only the
  ports in `CORS_ORIGINS` work. Any other port fails every request with a CORS error and looks like
  a backend outage.
- **A test that starts a scheduler drops a `scheduler_jobs.db` wherever it runs.** `tests/conftest.py`
  blanks `scheduler_jobstore_url` for the whole suite, so an in-memory store is the default; a test
  that wants persistence points it at `tmp_path` itself.
- **`sqlite:////tmp/x.db` in Git Bash lands in `C:\tmp`, not the shell's `/tmp`.** The SQLAlchemy URL
  is read by Python, which does not apply the MSYS path translation, so a stray file goes somewhere
  `ls /tmp` will not show it.
- **`TZ=Europe/Berlin date` silently returns UTC in Git Bash.** It does not error and it does not
  warn — `TZ=America/New_York` prints the same time — so any script reasoning about the Berlin sync
  slots from the shell clock is two hours out in summer, in the direction that permits a collision.
  Use Python's `zoneinfo` (`ops/finish-deploy.sh` has the helper).

## Recent sessions (last 5)

One line each, newest first. **Drop the oldest rather than growing this list** — `git log` holds the
detail; this exists so the next session knows what just moved without reading it. Distinct from the
*Shipped* section above, which is actionable (what to check on prod, and what has already been
confirmed) and gets deleted once nothing in it is outstanding: these lines are permanent, so don't
"tidy up" the overlap by deleting the wrong one.

- **2026-07-31** — enterprise-readiness pass: shared TTM growth,
  locale-independent chart dates, inception read from the data, keyboard/ARIA across the tab strip and
  every collapsible and sortable header, four more explicit error states, optional write auth +
  per-IP rate limit + request ids + `/health` build identity, the Activity ledger over the four
  unread tables, a persistent scheduler job store, delta-chip and scroll-affordance consolidation,
  real product chrome, a completed `/api/dividends/summary` contract, and a code-split bundle. Suites
  357 → 451 backend, 45 → 91 frontend; verified against a prod snapshot and in a real browser, which
  found three defects the green suite did not.
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
