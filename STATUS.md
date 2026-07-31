# Working state

**Last updated: 2026-08-01 (overnight loop, unpushed — see *Unpushed*)**

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

- **Push the remaining commit(s).** `git push` is **refused to an agent by the permission
  classifier**, so this is always a human step — not an oversight when you find work sitting
  unpushed. `git log --oneline origin/main..main` is the list.

  `ops/finish-deploy.ps1` (PowerShell) and `ops/finish-deploy.sh` (Git Bash) are equivalent twins
  that run push / token / guard in the only safe order and skip whatever is already done.
  **Keep the two in step if you change either.** Both take Berlin time from a real timezone
  database rather than the shell, because Git Bash on Windows silently ignores `TZ=` and returns
  UTC — a two-hour error in the direction that permits a collision.

  Note the scripts define `$k`/`$h` shorthand *inside one session*; pasting a later command into a
  fresh shell silently passes empty strings and `scp`/`ssh` print usage. Use literal paths, or
  re-run the script.

- **Rotate the IBKR Flex token.** It travelled as a `t=` URL parameter into `sync_runs.message` and
  was served by the public `/api/scheduler/history` until the 2026-07-28 scrub. `app/redact.py` now
  redacts on write *and* on read, so it cannot recur — but redaction cannot un-leak what was already
  reachable. Only Simon can rotate it (IBKR portal → Reports → Settings → Flex Web Service).
- **Backfill the 2025 tax year.** The Flex Query period cannot reach it, so 2025 correctly reports
  `dividend_source='yfinance_estimate'`. Needs a one-off period change on the query (or a browser
  download ingested via `app/cli/ingest_flex_xml.py`), then set it back to the rolling window.
  Ingestion is idempotent, so this is safe to repeat. The UI no longer hardcodes 2024 as the earliest tax year —
  both it and the chart's ALL range read `min(taxlots.open_date)` — so the backfilled year appears
  on its own once ingested.

## Watching

- **The `1001` problem is fixed — the Flex Query period is now `Last 30 Calendar Days`.** Confirmed
  by as clean an A/B as production allows: **20:00 error, 21:08 success, same token, same hour band,
  68 minutes apart, only the period changed.** 15:08 New York is mid-session, the window that had
  gone 0-for-8 that day. Statement shape went ~290 trade rows → 103 and ~107 cash transactions → 17.

  The cause was **the query growing from one section to six between 07-24 and 07-28** (Trades,
  CorporateActions, CashTransactions, then Deposits & Withdrawals and Transfers). Five of those scan
  the whole period; Open Positions, the only original section, does not — which is why years of
  YTD queries never provoked it. A *separate* change made it look worse than it was: the 13:00/20:00
  retry slots were added in `67e6a59` on 07-25, the same day `sync_runs` persistence landed, so new
  failing slots and first-ever visibility arrived together.

  Verified after the switch: all 71 YTD trades still on record month-by-month, `coverage_from` still
  2026-01-09, `taxlots_skipped: 0`, 979 lots. Nothing was lost.

  **Still worth confirming**: that 00:00 and 06:00 succeed on a normal night. And don't reason about
  statement cost from row counts — Open Positions is ~70% of the rows and ~0% of the scan work.
- **`find_stale_ibkr_sync` is now the thing that tells you a bounded window is drifting.** It warns
  after 7 days with no successful IBKR sync. Treat it as a prompt to download the statement from
  Client Portal and run `app/cli/ingest_flex_xml.py` — that path is idempotent, so re-ingesting a
  YTD export simply fills whatever the 30-day window missed. Real recovery, not a theoretical one,
  which is why a 30-day window is a comfortable choice rather than a tight one.
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

## Shipped 2026-07-31 — DEPLOYED and verified

Live at 19:31 Berlin. Suites: backend 357 → 462, frontend 45 → 91, `tsc -b` and `npm run build`
clean. **Write auth is ON in production** — verified from outside the host: a write with no key and
a write with a wrong key both 401, reads still 200. All five scheduler jobs re-registered after the
rebuild, which is the persistent job store doing its job. **The guarded `auto-deploy.sh` is
installed** on the VPS at 20:11 Berlin (5140 bytes, `-rwxr-xr-x`, byte-identical to `ops/`), so
deploys now defer rather than landing inside a sync slot.

Two things about that deploy worth knowing, both cost time on the day:

- **`commit` reads `unknown` on this one deploy, and that is expected.** `deploy.sh` pulls the repo
  *itself* (line 13), so the copy already executing is the one from before the pull — bash does not
  reload a running script. Any deploy that changes `deploy.sh` therefore runs the **old** logic once,
  and the `GIT_COMMIT` export it gained is missing for exactly that run. The next deploy stamps the
  real sha. The finish-deploy scripts now accept `unknown` + the `write_auth_enabled` marker as
  proof the new build is live, instead of hanging 15 minutes over a cosmetic stamp.
- **`docker compose restart` does not reload `env_file`.** Compose reads it when it *creates* a
  container; `restart` reuses the existing one with its original environment. So `API_ADMIN_TOKEN`
  landed in `.env` and was silently ignored — `write_auth_enabled` stayed `false` while everything
  reported success. **`docker compose up -d`** is required. Both scripts now use it *and* re-check
  `/health` afterwards rather than assuming, because the failure is invisible: a site whose write
  API is still wide open looks exactly like one that is locked down.

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

## Watch after the next deploy

- **The scheduler job store survived its first rebuild** — `/api/scheduler/status` listed all five
  jobs immediately after. Still worth one look on the *next* deploy for the other half of the claim:
  the container logs should show `kept, next run:` rather than recomputing, which is what proves a
  missed slot would actually be recovered instead of silently rescheduled forward.
- **`commit` should read a real sha next time, not `unknown`** — see *Shipped* above. If it still
  says `unknown` after a deploy that did **not** touch `deploy.sh`, then `GIT_COMMIT` genuinely is
  not reaching the container and the build-identity feature is broken rather than bootstrapping.
- **The newly-installed `auto-deploy.sh` has never actually fired.** It went on at 20:11, between
  slots. Confirm on the next deploy that `/root/auto-deploy.log` still logs a normal run — and,
  when one lands near 08/13/15/20/22:00, that it logs `SKIP: within 10min` and defers rather than
  stalling. A guard that refuses *every* deploy would look identical to "nothing was pushed".

## Unpushed — waiting on a human

An autonomous overnight loop ran on 2026-07-31 (`/loop 10m`): feature research → implementation → bug
hunting. Its commits are **local and unpushed on purpose** — a push auto-deploys inside 10 minutes and
nobody was awake to watch it. `git log --oneline origin/main..main` is the list; the loop's own running
notes are `.claude/overnight-log.md` (gitignored).

**The durable rules from this work now live in CLAUDE.md**, under *Client-side analytics — risk,
targets, currency* and the naive-UTC paragraph in *Database schema*. They are not repeated here, so
this section can be deleted once the commits are pushed without losing them.

### Three features, all frontend-only, none able to reach a provider

- **A risk row on the Performance tab** — volatility, Sortino, beta vs the primary benchmark, the
  *current* drawdown with the worst as its footnote, Herfindahl effective holdings. Beta reuses the
  benchmark series the chart already fetches, so it adds no request.
- **Target allocation & drift** on the Allocation tab — editable target per position, tolerance band,
  the signed trade that closes each gap, "adopt current weights". Targets in localStorage.
- **Currency exposure** on the Allocation tab — the book by the currency each listing trades in, led by
  the share quoted outside the base currency.

### Four bugs found and fixed

- **The whole codebase read the clock in local time** — 49 sites of `datetime.now()` against a
  naive-UTC convention, correct in production only because `python:3.11-slim` sets no `TZ`. Fixed via
  `app/clock.py`; `tests/test_clock_convention.py` walks the tree so it cannot return.
- **`SOXQ` had no ETF look-through entry**, so a holding bought 2026-07-27 was absent from the sector
  *and* geographic treemaps and counted as a stock in the third. No sync could have fixed it — the
  missing data is a mapping, not a fetch.
- **The rebalance panel built a plan out of a backend outage**, reporting *0 positions outside the band*
  above rows reading *Not currently held*. Caught by `e2e/errors`, which now covers it.
- **`e2e/a11y.mjs` claimed "backend optional"** and never could have been: three of its checks need one,
  so run as documented it reported 11/14 with every failure a phantom.
- **Analyst ratings were read out of yfinance by row position.** `recommendations.iloc[0]`, under a
  comment asserting row 0 *is* the current month — provider ordering taken on trust, and the same shape
  as the `openDateTime` defect CLAUDE.md says not to reintroduce. A three-month-old consensus reported
  as current is a plausible number, so nothing would look wrong. Now keyed on `period == '0m'`, and a
  frame that has the column but no current row reports **nothing** rather than an older period. Also
  `int()` on a NaN raised inside a broad `except`, so one unparseable column discarded all five counts
  and the security's rating with them.
- **The two endpoints reporting PEG disagreed about how to compute it.** `FundamentalsService` and
  `WatchlistService` both fall back when Yahoo gives no `pegRatio`, and their orders had drifted: the
  watchlist tries forward-EPS growth (its own comment calls that tier *"preferred"*) before the analyst
  5-year CAGR, while fundamentals went straight to the CAGR with **no forward-EPS tier at all**. So one
  security could show a PEG on `/api/watchlist` and a different one, or none, on
  `/api/fundamentals/portfolio` — the same defect, between the same two services, that `ttm_growth.py`
  was extracted to end. Closing it cost **nothing**: fundamentals already fetches `growth_estimates`
  and already computes `fwd_eps` for its own column; it just never fed it to the fallback.
  `app/services/peg_ratio.py` now holds the arithmetic so it cannot drift again.
- **A fallback price claimed Yahoo's provenance.** `fetch_and_cache_prices` wrote
  `source='yahoo_finance'` for every cached row, with a comment conceding the truth (`# or
  'alpha_vantage' if from fallback`) — and the fallback is **live**, since `ALPHA_VANTAGE_API_KEY` is
  set in `backend/.env`. So a fallback row misreported the provider in the column every pricing
  diagnosis reads first. Two related defects went with it: the fallback **stamped `security.currency`
  onto its prices unchecked** while querying by bare US symbol — the exact SBI mechanism, fixed for
  Yahoo in July and not here, so it now refuses a non-USD security rather than adopting an
  unverifiable label — and `MarketPrice.source` **defaulted to `"alpha_vantage"`**, the fallback
  provider. See CLAUDE.md's rule 1, which now says Yahoo is not the only provider.
- **Any validation error reached the user as `[object Object]`.** FastAPI sends a 422's `detail` as an
  **array of objects** (an ordinary `HTTPException` sends a string, which is why it went unnoticed), and
  `api.request()` passed it straight to `new Error()`. `describeErrorBody` now renders it as
  `year: Input should be a valid integer`, and a non-JSON error page reports its real status instead of
  the literal string "Unknown error". Verified against the running backend, not assumed.
- **A failed `/api/settings` fetch silently mislabelled every money figure for the whole session.**
  `CurrencyContext` fetches with `staleTime: Infinity` — correct, since the value only changes through
  our own mutation, but it makes one failed fetch sticky rather than a blink. The provider fell back to
  `'EUR'` and said nothing, so a CHF account renders `€` over franc figures: **numbers right, label
  wrong**, with nothing on screen inviting doubt. `currencyIsAssumed` now says so beside the selector,
  and only once the fetch has actually failed — in flight the fallback is a placeholder, not a claim.
  Pinned in `e2e/errors.mjs`, and the context had no tests before (9 now).
- **`formatDate` shifted every date a day west of Greenwich.** `new Date("2026-03-14")` parses a
  date-only string as UTC midnight and `Intl` renders it in local time, so the portfolio chart labelled
  every point a day early for any viewer in the Americas — and 1 January as 31 December. The **mirror**
  of the bug `lib/dateRanges.ts` exists to fix (that one serialised local *to* UTC and started YTD early
  in positive offsets; this parses *from* UTC and labels early in negative ones). Invisible from Berlin,
  which is why it survived. `lib/utils.ts` had no tests at all; it has 25 now.

### Wants Simon's eye

- **SOXQ's geographic split in `app/etf_mappings.py` is my estimate** (US 80 / Taiwan 10 / Netherlands 8
  / Korea 2), skewed more US than SMH's because the PHLX SOX index only takes US-listed names. The
  sector (100% Technology) is unambiguous for a pure semiconductor fund; the geography is approximate
  like the rest of that file. Adjust if you want it tighter.
- **Allocation targets are stored in localStorage, not the database.** Chosen because `/api/` is public
  and auth-gated, so a route storing portfolio intent is a larger surface than the feature earns — but
  it means targets do not follow you to another browser. Reversible: the lib is pure and takes a plain
  map, so a table plus endpoint would only change where that map comes from.

### Verified and **not** bugs — recorded so nobody re-chases them

`ActivityTab`'s `amount_base ?? 0` (unreachable — `BaseFx.convert` never returns `None`);
`DividendKpiCards`' `prev_net_eur ?? 0` (over-permissive TS type; the backend always emits a float);
`PortfolioValuePoint.external_flow_eur`'s `0.0` model default (the service supplies it on every row);
the first timeline row's flow (already fixed by the pre-window seeding loop); the success-path
`SyncRunRepository.record()` outside the `try` (identical in **all five** CLIs, so a deliberate pattern);
a currency switch's unfiltered `invalidateQueries()` (roughly 20 refetches against a 120/min limit, and
it cannot reach Yahoo because the benchmark timeline cache stays EUR while `_apply_base_currency` is a
display projection — so a currency change is always a cache hit); that same call overwriting the
optimistic `setQueryData` for `['settings']` with a refetch, so **the server's reply wins rather than the
mutation's** (correct, and the reason a test mocking a stale reply asserts the opposite);
`expire_on_commit=False` making post-commit attribute reads safe; `security.asset_type` and
`security.asset_category` both being real columns; `_add_to_category` merging by symbol (which is what
correctly combines a dual-listed ASML inside one category); and `lib/monthlyReturns.ts` already routing
through `externalFlow`.

**`benchmark_service.calculate_benchmark_value_over_time()` was audited line by line and is correct** —
it is the input to the new beta metric and re-reading 200 lines is expensive, so: close events exclude
**on** the close date like everywhere else; pre-window events fold in on the first iteration without
needing `portfolio_service`'s explicit seeding loop; share and cost events are appended *and skipped*
together, so a zero value can never be emitted against a live cost basis; and `_apply_base_currency`
converts all four money fields and recomputes the gain from the converted pair, so it is **not** the
CAD/CHF half-conversion shape. One behaviour to know: when shares are held but the index price or FX
rate is missing, that day is **omitted from the series** rather than zeroed — `betaAndCorrelation` skips
such a pair by design, and the date stays in `missing_dates` so it self-heals.

### State

**Do not add `@vitest/coverage-v8` to `frontend/`** to measure frontend coverage — a devDependency there
is installed by `npm ci` on every `--no-cache` deploy, which is the trap `e2e/` is a separate package to
avoid. Listing source modules with no corresponding test file is the zero-install proxy, and it found
three of this session's bugs. **That lens is now exhausted**: every `lib/` module has tests. What is
still untested is the large tab components, whose logic lives in the `lib/` modules they call and is
additionally exercised by `e2e/sweep`.

**Verified in one consolidated pass at the end of the session**, not just incrementally: backend
**556**, frontend **268**, `tsc -b` and `npm run build` clean, and every runnable browser script back to
back — `a11y` 17/17, `sweep` 16/16, `errors` 15/15, `chunks` 33/33, `csp` 4/4. Only `ledger` was not
run; it needs a production snapshot, which is real account data. **Nothing is deployed** — all of this
is local. Every local server was started with `SCHEDULER_ENABLED=false` confirmed in `.env` *and* in
`/health`, and stopped afterwards; no provider was contacted at any point.

**The aggregate diff has been read as well as tested** — 52 files, +4322 / −157, no stray artifacts, no
debug leftovers, no focused or disabled tests. The public-repo audit passed the half that is expensive
to re-establish: **no database is tracked now and none was ever committed in history**, and there are no
stray data files. It did turn up one doc defect, since fixed: `backend/portfolio.db` is gitignored and
untracked, but five places called it "checked-in" — so a fresh clone has *no* database, the backend
creates an empty one, and `e2e/a11y` fails for want of rows in a way that looks like a regression.

`tests/test_api_contract_drift.py` now fails when a TS interface reads a field the backend stopped
sending — a generalisation of the dividend contract test to all 25 name-matched model/interface pairs,
with no hand-maintained list. It found **no drift** on the current tree, so it ships as a guard rather
than a fix. Frontend-only fields fail (the silent `undefined`); backend-only ones are printed and
allowed, since the wire may legitimately carry more than any screen renders.

Coverage-led hunting found two of the bugs (`pytest --cov`, backend ~70%). The last flagged gap,
`taxlot_repository` (58%), turned out to be **dead code rather than untested code**: four methods with no
caller anywhere, three of them traps for whoever reaches for the obvious name — `close_taxlot` wrote a
closure with no `close_source` (the shape `restamp_unsourced_closed_lots()` repairs),
`delete_by_security_id` deleted *closed* lots that the contributions splice needs to survive, and
`get_taxlots_on_date` was a fourth uncalled copy of the exclude-on-close convention CLAUDE.md says to
change in lockstep. Removed rather than tested: coverage would have pinned behaviour that should not be
reachable.


## Worth doing next

Rough priority. The auto-deploy install moved to *Needs a human* — it is the last deploy step.

1. **Fold `PRE_OWNERSHIP_HISTORY_YEARS` pruning into a scheduled job — reassess before building.**
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
- **Use a snapshot of the production DB, not the local `backend/portfolio.db`** — the latter predates
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
- **Every position in the local `backend/portfolio.db` has `market_price: null` and a market value of
  0.00.** So the currency-exposure card reports *no priced positions* and the rebalance panel shows 29
  unpriced rows — both correct, and both easy to mistake for a broken feature. Anything that depends on
  a valued portfolio can only be browser-verified against a production snapshot.
- **uvicorn can die mid-Playwright-run with `OSError: [WinError 64] The specified network name is no
  longer available`** — a Windows asyncio-proactor reaction to an abruptly closed connection, not a code
  fault. The e2e script then reports `ERR_CONNECTION_REFUSED` and a shrunken panel, which reads exactly
  like a regression in whatever you just wrote. **Confirm `/health` still answers before believing an
  e2e failure.**
- **A test helper with a default parameter swallows an explicitly-passed `undefined`**, so
  `renderCard(undefined)` renders the default fixture and any "backend down" assertion silently tests the
  loaded state instead. `CurrencyExposureCard.test.tsx` keeps a separate `renderUnloaded()` for this.
- **A jsdom test that renders `ScrollableTable` needs a `ResizeObserver` stub**, and a component test
  that renders anything using `useBaseCurrency`/`useCurrencySymbol` needs a `QueryClientProvider`
  *above* `CurrencyProvider` — the provider reads the base currency through TanStack Query, so
  wrapping in `CurrencyProvider` alone throws `No QueryClient set`. Neither is a component defect:
  `ResizeObserver` has been in every browser since 2020, so guarding production code for jsdom's gap
  would be wrong. `RebalanceCard.test.tsx` has both patterns to copy.
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

- **2026-07-31 (overnight, unpushed)** — autonomous loop: three frontend features (risk row, target
  allocation & drift, currency exposure) and ten bugs (49 sites reading the clock in local time; SOXQ
  missing from the ETF look-through; the rebalance panel building a plan out of an outage; `e2e/a11y`'s
  "backend optional" claim). Suites 462 → 587 backend, 91 → 268 frontend; all `e2e` scripts green bar
  `ledger`. Durable rules promoted into CLAUDE.md. **Nothing deployed** — see *Unpushed*.
- **2026-07-31** — enterprise-readiness pass: shared TTM growth,
  locale-independent chart dates, inception read from the data, keyboard/ARIA across the tab strip and
  every collapsible and sortable header, four more explicit error states, optional write auth +
  per-IP rate limit + request ids + `/health` build identity, the Activity ledger over the four
  unread tables, a persistent scheduler job store, delta-chip and scroll-affordance consolidation,
  real product chrome, a completed `/api/dividends/summary` contract, and a code-split bundle. Suites
  357 → 462 backend, 45 → 91 frontend; verified against a prod snapshot and in a real browser, which
  found three defects the green suite did not. **Deployed the same evening**: write auth on and
  enforced, guarded auto-deploy installed, five scheduler jobs surviving the rebuild.
- **2026-07-30** — two batches: five audit fixes (Yahoo gating, `openDateTime` off ibflex, SELL beats
  the cost-conserved heuristic, tax-report honesty, dividend card net), then the SBI dividend bug —
  poisoned estimates purged on prod, mapping changes now retire the rows they produced, source-aware
  dividend key, provenance detector, batched price/lot writes, forecast/yield qualifiers. Suite
  313 → 357, deployed and verified. Lost the 08:00 full_sync to a deploy landing in the slot.
- **2026-07-29** — correctness sweep (16 fixes) plus dividend growth (MoM/YoY) and the DividendsTab
  rebuild; scheduler gated behind `SCHEDULER_ENABLED`; STATUS.md split out of CLAUDE.md.
- **2026-07-28** — external cash ledger live on prod (deposits ingested, transfers excluded) and the
  money-in splice; Dividends tab + breakdown endpoint; Flex token redacted from stored and served errors.
