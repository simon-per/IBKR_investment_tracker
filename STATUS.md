# Working state

**Last updated: 2026-07-29**

`CLAUDE.md` is the durable guide — architecture, invariants, and the rules that were each a bug
first. **This file is the perishable half**: where the work actually stands, what is known-broken,
and what is worth doing next. Read both at the start of a session; update this one at the end.

Rules for keeping it useful: **delete entries once they stop being true** rather than accumulating
history, and **describe figures rather than publishing them** (the repo is public, the base currency
is user-switchable, and a pasted total goes stale silently — check the API or the DB instead).

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

## Worth doing next

Rough priority. None of these are started.

1. **Growth chips for portfolio value and contributions**, in the same visual language as the
   Dividends tab (`DeltaChip`, `lib/delta.ts`). Explicitly deferred when the dividends work was
   scoped — the pattern now exists and is tested, so this is mostly wiring.
2. **Commit the visual-regression harness.** The Playwright screenshot loop that verified the
   Dividends tab lives *outside* the repo, so it is not reproducible from a clean checkout. It cannot
   simply become a `frontend` devDependency: `deploy.sh` runs `npm ci` on a `--no-cache` rebuild and
   Playwright's postinstall pulls ~150 MB of Chromium, which would tax every 10-minute deploy. Needs
   a separate package or a skipped-download flag.
3. **A horizontal-scroll affordance on the wide tables.** The dividends position table has ten
   columns and scrolls inside its own container at narrow widths, with nothing hinting that it can.
4. **Fold `PRE_OWNERSHIP_HISTORY_YEARS` pruning into a scheduled job.** `prune_empty_dividends.py`
   is a manual CLI; the ingest window now prevents new junk, so this is cleanup-only and low value.

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
