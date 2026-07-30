# Working state

**Last updated: 2026-07-30**

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

- **Rotate the IBKR Flex token.** It travelled as a `t=` URL parameter into `sync_runs.message` and
  was served by the public `/api/scheduler/history` until the 2026-07-28 scrub. `app/redact.py` now
  redacts on write *and* on read, so it cannot recur — but redaction cannot un-leak what was already
  reachable. Only Simon can rotate it (IBKR portal → Reports → Settings → Flex Web Service).
- **Backfill the 2025 tax year.** A YTD Flex Query cannot reach it, so 2025 correctly reports
  `dividend_source='yfinance_estimate'`. Needs a one-off period change on the query (or a browser
  download ingested via `app/cli/ingest_flex_xml.py`), then set it back to YTD. Ingestion is
  idempotent, so this is safe to repeat.

## Watching

- **IBKR `1001` on the retry slots.** Four consecutive failures on 2026-07-29 (11:00 and 18:00 UTC
  among them). This is documented flaky behaviour, not a regression: `1001` at the *request* step is
  fatal-fast on purpose, and the schedule is designed so a later slot recovers. The **08:00
  `full_sync` is the dependable slot** — if that one also starts failing, use the offline XML path
  rather than retrying, which is what caused three token lockouts historically.
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

## Just landed (2026-07-30) — needs a live look after the next deploy

Two batches today. The earlier five (Yahoo gating, `openDateTime` off ibflex, SELL-beats-heuristic,
tax-report honesty, dividend card net) are **deployed and verified on prod**. The second batch is the
SBI dividend bug and its root cause; suite 313 → 357. What to eyeball:

1. **SBI's forecast is deliberately empty.** The two poisoned estimate rows were purged on prod
   (`manual_dividend_purge`, 2026-07-30). Income was unchanged to the cent — portfolio net 66.87 before
   and after — and the forecast went 5 payouts / 12.17 → 0. **That emptiness is correct**, not a
   regression: one IBKR payment cannot establish a cadence. It fills in when a second real payment
   arrives, or when a genuine `SBI.TO` dividend series is fetched. Don't "fix" it.
2. **A `DIVIDENDS PREDATE MAPPING` warning may appear** in market-data sync warnings for any other
   security in the same shape. That is the new detector working; purge and let it refetch.
3. **The dividends table has two new markers** — `n=2` on a thin forecast inference and `†` on a
   partial-year trailing yield. Both are expected on recently-bought holdings.
4. **A migration runs on the next deploy** (`o8d5f2a9b3c4`, `p9e6a3b0c4d5`): the dividend unique key
   becomes source-aware, `ticker_mappings` gains timestamps, and `taxlots.close_date` gets an index.
   Verified against a data-carrying copy, and auto-deploy backs up the DB first — but this is the one
   change worth confirming came up clean.

## The 2026-07-30 08:00 full_sync was lost

Pushing at 06:00 UTC deployed straight into the 08:00 Berlin slot, and `/api/scheduler/history` has no
`full_sync` row for that day. Today's 730-day price refresh and yfinance dividend sync did not run, and
both IBKR slots failed `1001`. Tomorrow's 08:00 recovers it. This is the documented trap firing exactly
as described — see *Worth doing next* for the two fixes that would stop it.

## Worth doing next

Rough priority. Item 8 is written but not installed; the rest are not started.

1. **Growth chips for portfolio value and contributions**, in the same visual language as the
   Dividends tab (`DeltaChip`, `lib/delta.ts`). Explicitly deferred when the dividends work was
   scoped — the pattern now exists and is tested, so this is mostly wiring. Note it is a
   *consolidation*, not pure wiring: `ContributionsStrip.tsx:108` already hand-rolls a competing chip
   (`+7%` where `DeltaChip` renders `▲ +7.4%`), so that duplicate has to go at the same time.
2. **Commit the visual-regression harness.** The Playwright screenshot loop that verified the
   Dividends tab lives *outside* the repo, so it is not reproducible from a clean checkout. It cannot
   simply become a `frontend` devDependency: `deploy.sh` runs `npm ci` on a `--no-cache` rebuild and
   Playwright's postinstall pulls ~150 MB of Chromium, which would tax every 10-minute deploy. Needs
   a separate package or a skipped-download flag.
3. **Four collapsible cards cannot be opened without a mouse.** `MonthlyReturnsHeatmap.tsx:134`,
   `MonthlyDeploymentCard.tsx:65`, `DividendSummary.tsx:107` and `PerformanceAttribution.tsx:54` put
   `onClick` on `<CardHeader>` with no `tabIndex` / `role` / `onKeyDown` / `aria-expanded`, so Monthly
   Returns, Monthly Deployment, Dividend Income and Performance Attribution are keyboard-unreachable.
   Sortable `<th>`s in `FundamentalsTab.tsx:93` and `WatchlistTab.tsx:185` have the same problem, and
   Watchlist's metric-definition tooltips are `onMouseEnter`-only — the only place PEG/RSI/TTM-growth
   are defined. `PositionsList.tsx:178` already solves this properly with a real `<button>` inside the
   `<th>`; lift and reuse it. `ui/tabs.tsx:31` has no `role="tablist"` / `aria-selected` either.
4. **Four more surfaces let a backend failure look like empty data** — `ContributionsStrip.tsx:49`
   (returns `null`, so the strip just vanishes), `MonthlyDeploymentCard.tsx:78`,
   `DividendSummary.tsx:123`, and all four `FundamentalsTab` queries ("Click Sync Now"). Six other
   components already fixed this class with explicit comments; this finishes the job. `TaxTab` got its
   version on 2026-07-30, so the pattern to copy is right there.
5. **YTD and MTD start a day early in any positive-UTC-offset timezone.** `Dashboard.tsx:58-76`:
   `new Date(now.getFullYear(), 0, 1).toISOString()` is local midnight serialised as UTC, so Berlin
   gets `2025-12-31` and New York gets `2026-01-01` for the same click. Same portfolio, different
   numbers by locale. (A 31 Dec base is arguably the *right* YTD convention — the bug is that it is
   accidental and locale-dependent, so pick one deliberately.)
6. **`_ttm_growth_from_quarterly` is duplicated and divergent.** `watchlist_service.py:157` has a
   5–7-quarter fallback tier that `fundamentals_service.py:85` lacks, so one security can report
   different earnings growth on `/api/fundamentals/portfolio` and `/api/watchlist`.
7. **A horizontal-scroll affordance on the wide tables.** The dividends position table has ten
   columns and scrolls inside its own container at narrow widths, with nothing hinting that it can.
   Scope is wider than it looks: `WatchlistTab` is 18 columns.
8. **Install the guarded auto-deploy script — WRITTEN, NOT INSTALLED.** `ops/auto-deploy.sh` is now
   in the repo (it previously existed only as `/root/auto-deploy.sh`, unversioned and unreviewed
   despite governing every deploy) and adds the sync-slot guard: it refuses to deploy within 10
   minutes either side of a Berlin slot and defers to the next tick, which is what would have saved
   today's `full_sync`. The boundary logic is tested across all five slots, the quiet hours and the
   midnight wrap. **The VPS still runs the old copy** — installing it changes deploy behaviour, so it
   needs a deliberate step:

       scp ops/auto-deploy.sh root@<host>:/tmp/ && ssh root@<host>          'install -m 755 /tmp/auto-deploy.sh /root/auto-deploy.sh'

   Verify afterwards by watching `/root/auto-deploy.log` for a `SKIP: within 10min` line near a slot.
9. **Persist the scheduler's job store.** The real fix behind the above: APScheduler runs in-process
   with an in-memory store, so any restart drops whatever slot it overlapped. A `SQLAlchemyJobStore`
   with `coalesce=True` and a `misfire_grace_time` would run the missed job on startup instead of
   losing it. CLAUDE.md's "don't push near a slot" is a human workaround for a missing feature, and it
   has now failed once in practice.
10. **Fold `PRE_OWNERSHIP_HISTORY_YEARS` pruning into a scheduled job.** `prune_empty_dividends.py`
   is a manual CLI; the ingest window now prevents new junk, so this is cleanup-only and low value.

Also noted, not yet items: `Dashboard.tsx:84` hardcodes the ALL-range start at `2024-05-28` while
`TaxTab.tsx:10` hardcodes `FIRST_TAX_YEAR = 2024` — transferred lots keep their **original**
`open_date`, so check both against `min(taxlots.open_date)` before the 2025 backfill lands.
`CLAUDE.md` says React 18; `package.json` pins `react@^19.2.0`.

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
  in ~90 s with APScheduler in-process, so an overlapping deploy silently loses that sync.

## Recent sessions (last 5)

One line each, newest first. **Drop the oldest rather than growing this list** — `git log` holds the
detail; this exists so the next session knows what just moved without reading it. Distinct from
*Just landed* above, which is actionable (what to eyeball on prod) and gets deleted once verified:
these lines are permanent, so don't "tidy up" the overlap by deleting the wrong one.

- **2026-07-30** — two batches: five audit fixes (Yahoo gating, `openDateTime` off ibflex, SELL beats
  the cost-conserved heuristic, tax-report honesty, dividend card net), then the SBI dividend bug —
  poisoned estimates purged, mapping changes now retire the rows they produced, source-aware dividend
  key, provenance detector, batched price/lot writes. Suite 313 → 357. Lost the 08:00 full_sync to a
  deploy.
- **2026-07-29** — correctness sweep (16 fixes) plus dividend growth (MoM/YoY) and the DividendsTab
  rebuild; scheduler gated behind `SCHEDULER_ENABLED`; STATUS.md split out of CLAUDE.md.
- **2026-07-28** — external cash ledger live on prod (deposits ingested, transfers excluded) and the
  money-in splice; Dividends tab + breakdown endpoint; Flex token redacted from stored and served errors.
- **2026-07-27** — SBI mapping repair: reject a Yahoo ticker quoting a different currency than the
  security, second FX provider fallback for currencies the ECB set lacks, `manage_mappings` CLI for
  the last table still edited by hand. (Prices were purged here; the dividend rows were not — that
  half surfaced on 07-30.)
- **2026-07-26** — third Flex token lockout, self-inflicted: stop re-requesting after `Code=1001` and
  poll the same reference instead; offline XML ingest added as the escape hatch.
