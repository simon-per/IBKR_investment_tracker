# IBKR Portfolio Analyzer — Project Guide

Full-stack portfolio tracker for an Interactive Brokers account. Tracks securities, tax lots, trades,
corporate actions and dividends; renders cost-basis vs. market-value charts; and produces a Swiss tax
report. All values are stored in EUR and projected into a base currency the user switches at will
(`app_settings.base_currency`, EUR/CHF/USD) — so **read it from `/api/settings`, never from this file**;
it has been both CHF and EUR, and every money figure moves with it.

**Live:** https://portfolio.srv1211053.hstgr.cloud · **Repo is PUBLIC** (never commit account data)

**Read [STATUS.md](STATUS.md) too, and leave it accurate before you stop — see
[Keeping STATUS.md current](#keeping-statusmd-current), which is not optional.** This file is the
durable half — architecture and the invariants that were each a bug first. STATUS.md is the
perishable half: what is in flight, what is known-broken, what needs a human, and the local-dev
traps that keep costing time.

---

## ⚠️ Two rules that must never be broken

### 1. Never call Yahoo Finance without explicit user permission
`yfinance` powers market prices, dividend estimates, fundamentals and benchmarks. Yahoo rate-limits
hard (~500-2,000 requests/hour, ~10-20 in a burst, IP-based). A full market-data sync is **50-150+
requests**. Symptoms of a limit: HTTP 429, HTTP 404 with `Expecting value: line 1 column 1 (char 0)`,
empty JSON, timeouts. Recovery: **stop immediately, wait 30-60 min.**

Protections in `market_data_service.py`: random 1-3s delay per request, 2-4s between securities, Chrome
User-Agent, rate-limit detection that aborts the run, and incremental caching (only missing dates).
`yfinance` must stay **>= 1.1.0**.

The IBKR Flex sync (`POST /api/sync/ibkr`) is Flex-only and touches **no** Yahoo — it's always safe.

### 2. Never loop the IBKR Flex sync
IBKR allows **1 request/second and 10 requests/minute per token**, and one `ibflex.client.download()`
is *several* HTTP requests (request statement, then poll until ready, each with 3 internal tries). An
eager retry loop blows the cap and triggers **`Code=1025: Too many failed attempts`** — an undocumented
token lockout lasting **hours** (observed ~14h) that blocks all syncing. This has happened **three times,
every one self-inflicted** — twice by looping `download()`, once by re-requesting after a `1001` (below).

Retrying *during* a lockout can extend it. When locked: do nothing and let the schedule recover it.

Budgets in `ibkr_service.py`: `_FLEX_RETRY_DELAYS = [30]` (2 attempts, interactive path) and
`FLEX_RETRY_DELAYS_PATIENT = [120, 300, 600]` (scheduled jobs). `1025` fails fast with guidance; `1018`
always backs off >= 60s. Pinned by `tests/test_flex_retry_policy.py`.

**`1001` means the opposite thing at each step, and getting that wrong caused a third lockout
(2026-07-26).** While *retrieving*, it means "not ready" — keep polling the same reference. From
*SendRequest*, it means IBKR tried to generate and failed, which is exactly what `1025` counts:

```
Code=1001 ...; attempt 1/4, re-requesting in 120s   ->   Code=1025 Too many failed attempts
```

So `1001` is in `_RETRIEVE_PENDING_CODES` but deliberately **not** in `_REQUEST_RETRYABLE_CODES` — it
fails fast and the next scheduled job asks for a fresh statement. With five IBKR attempts a day, giving up
costs hours of freshness; re-requesting costs a lockout of every sync. The codes still retryable at the
request step (`1009`/`1018`/`1019`/`1021`) all mean "throttled or busy, no generation job was created".

Genuine transport errors (`requests.RequestException`: DNS, reset, timeout) **are** retried — they never
reached IBKR, so they cost nothing against the token. Mid-poll they re-retrieve the same reference; before
a reference exists they re-issue SendRequest. A DNS blip used to kill a whole job.

### The two-step rule (why we don't use `client.download()`)

Flex is a two-step protocol: **`SendRequest`** asks IBKR to generate the statement and returns a
`ReferenceCode`; **`GetStatement`** retrieves it, answering "try again shortly" until it's ready. IBKR's
docs are explicit:

> "If statements are still being generated when you submit your request to retrieve them, you should
> **not re-initiate the Flex request**, but instead keep trying to **retrieve** the statement."

`ibflex.client.download()` polls correctly for `1009`/`1019`/`1018` but **not `1001`** — it raises, so any
outer retry calls `download()` again and starts a *brand-new generation job*. Do that a few times and
IBKR blocks the token: **`1025` counts failed *generations*, not request volume** (volume is `1018`,
which we never saw). The first two lockouts came from this; the third came from re-requesting on `1001`,
the same mistake one layer up.

So `IBKRService._download_statement()` drives the two steps itself using ibflex's public pieces
(`request_statement`, `submit_request`, `check_statement_response`, `STMT_URL`): **SendRequest once**,
then poll the *same* `ReferenceCode` for every `_RETRIEVE_PENDING_CODES` hit, bounded by a deadline
(120s interactive / 900s scheduled) rather than an attempt count. The outer loop only ever re-issues
SendRequest, and only for failures raised *before* a reference code exists — the one case where
re-initiating is unavoidable.

**Flex error codes:** `1001` statement not ready (transient, expected — poll, don't re-request),
`1003` not available (terminal), `1018` rate limit (1/sec, 10/min per token), `1019`/`1021` transient,
`1025` **undocumented** token lockout from repeated failures (fatal, never retry), `1012` token expired,
`1013` IP restriction, `1015` bad token. The official table stops at 1021 — 1025 appears nowhere in it.

---

## Keeping STATUS.md current

STATUS.md answers "where does this actually stand?", and it is only worth reading if it is true.
**Updating it is part of the work, not a courtesy afterwards.** The previous wording — "update it when
you finish a session" — named no trigger a session could recognise, so it got skipped.

**Leave it accurate before you stop, on any turn where your work changed what it should say:**

- code, config or a migration changed — and *Worth doing next* should lose whatever you just finished
- you shipped, reverted, or left something that needs watching after the next deploy
- you found something known-broken or flaky, or something only a human can do (rotate a token, change
  a Flex Query period, click through the IBKR portal)
- a *Known rough edge* stopped being true, or a new accepted-not-a-bug appeared
- you lost time to a *local-dev trap* that isn't in the list yet

A turn that only answers a question and finds nothing new needs no edit — but **discovering something
is a change of status even when no code moved**, so an audit that turns up real defects belongs in the
file whether or not they get fixed the same day.

**It is a snapshot, not a log.** Bump `Last updated`, add what became true, and **delete what stopped
being true** instead of stacking corrections. `Recent sessions` is the one append-only part, capped at
five one-liners — drop the oldest rather than letting it grow. And never accumulate **figures** (public
repo, user-switchable base currency, and a pasted total goes stale silently) or **what git already
records** — the log has what changed; STATUS.md has what is now true and what it costs the next person.
A count of unpushed commits is both, which is why it is written as `git log --oneline origin/main..main`
rather than a number: as a figure it went stale three times in one session, each time inside the very
commit that corrected it.

---

## Tech stack

**Backend** — FastAPI (async), SQLAlchemy 2.0 + aiosqlite (WAL), Alembic, APScheduler,
`ibflex` **0.15** (pinned), `yfinance` >= 1.1.0, Frankfurter API for FX.
**Frontend** — React 19 + TypeScript + Vite, TanStack Query, Recharts, Tailwind + shadcn/ui.
Vitest runs in `node` by default; component tests opt into jsdom per file with a
`// @vitest-environment jsdom` docblock, because the pure `lib/` tests are the large majority and
paying jsdom's startup for all of them is the wrong default.

**The bundle is code-split, and two of the boundaries are deliberate.** The seven non-default tabs
are `React.lazy` in `Dashboard.tsx` (safe because `TabsContent` returns `null` while inactive, so a
panel is not mounted until selected). **Recharts stays eager** — `PortfolioValueChart`,
`PerformanceAttribution` and `MonthlyDeploymentCard` are all on the default Performance tab, so
deferring it would only move the wait; don't "optimise" it into a lazy chunk. `manualChunks` in
`vite.config.ts` splits `react` / `charts` / `query` mainly for **caching**: the VPS redeploys within
10 minutes of any push and nginx serves `/assets/` `immutable`, so keeping vendor code out of the
app chunk took the per-deploy re-download from 264 kB gzipped to ~52 kB. List chunk members by the
specifier that actually appears in the graph (`react-dom/client`, `react/jsx-runtime`) — naming the
bare packages emits a 0-byte chunk and leaves React in the app bundle.

Because a lazy chunk can 404 after a redeploy (content-hashed names, page held open across a
deploy), every lazy panel is wrapped in `ui/LazyTabPanel.tsx` — a *scoped* boundary. Without it that
rejection reaches `App.tsx`'s app-level boundary and blanks the whole dashboard, which is worse than
the eager import it replaced. Chunk boundaries are a build-output property no unit test can see, so
the end-to-end check is `e2e/lazychunks.mjs`.

**`e2e/` is the browser-check package**, deliberately separate from `frontend/`: `deploy.sh` runs
`npm ci` inside `frontend/` on every `--no-cache` rebuild and Playwright's postinstall pulls ~150 MB
of Chromium, which a 10-minute deploy cadence cannot absorb. Nothing in the deploy path touches it.
It covers what the unit suites structurally cannot see — keyboard/ARIA on the assembled page, the
production CSP, chunk boundaries, and the backend-down pass asserting no surface falls back to an
empty-data message. Read `e2e/README.md` first: **the preconditions differ per script**, and two of
them (`csp`, `chunks`) must run against `vite preview` rather than the dev server, because the dev
server emits an inline react-refresh script that `script-src 'self'` correctly blocks and does not
produce chunk boundaries at all.

---

## IBKR Flex Query integration

### The Flex Query (`App_OpenLots`, ID 1389408)

Required sections and the fields the parsers actually read:

| Section | Options | Key fields |
|---|---|---|
| **Open Positions** | **Lot** | `conid`, `symbol`, `isin`, `description`, `currency`, `listingExchange`, `position`, `costBasisPrice`, `costBasisMoney`, `openDateTime`, `reportDate` |
| **Trades** | **Execution** | `conid`, `symbol`, `tradeDate`, `buySell`, `quantity`, `tradePrice`, `proceeds`, `ibCommission`, `currency`, **`fifoPnlRealized`** (= "Realized P/L"), `transactionID` |
| **Cash Transactions** | Dividends, Payment in Lieu, **Withholding Tax**, **Deposits & Withdrawals** | `type`, `conid`, `symbol`, `settleDate`/`dateTime`, `amount`, `currency`, `transactionID` |
| **Corporate Actions** | Detail | `type`, `conid`, `symbol`, `dateTime`/`reportDate`, `quantity`, `value`, `proceeds`, `actionDescription`, `transactionID` |
| **Transfers** | — | `type`, `direction`, `date`/`reportDate`, `cashTransfer`, `positionAmount`, `symbol`, `conid`, `company`, `transactionID` |

**Deposits & Withdrawals** feeds the contributions report; without it there is no record of external
money at all. **Transfers** exists only so an incoming broker transfer can be told apart from a deposit
— see the contributions section. Both are inert until parsed: `extract_cash_transactions` filters to the
three dividend types, so ticking them early cannot disturb anything.

**General config that matters:** Format **XML**; Period **Last 30 Calendar Days**;
Date `yyyyMMdd`, Time `HHmmss`, separator `;`. **Never use `dd/MM/yyyy`** — ibflex assumes US
`MM/dd/yyyy` for ambiguous formats and would silently swap month and day.

**The period was Year to Date until 2026-07-31 and must not go back** — that is what caused the
`Code=1001` failures (see *Sync schedule*). Trades/CashTransactions contain only rows *inside* the
period, so the window has to comfortably exceed the longest plausible run of failed syncs; 30 days
against three IBKR attempts a day is ~90 consecutive failures. Something very short like
"Last Business Day" would mean a single bad day loses trades permanently.

Prior tax years need a one-off period change (e.g. 2025), then set back. Ingestion is idempotent
(upserts keyed on `ib_key`), so re-syncing is safe — which is also the recovery if a bounded window
ever *does* miss something: download a wider statement from Client Portal and ingest it offline.

### Offline ingest — the escape hatch from a locked token

The Flex **Web Service** and the **download button** in Client Portal serve the same statement over
independent channels. Only the API path spends the token's request budget, so only it can trip `1025`.
So a statement saved from the browser can be ingested *during* a lockout — and since the browser download
uses whatever period you set, it is also the practical way to reach a prior tax year:

```bash
docker cp stmt.xml backend-portfolio-backend-1:/tmp/stmt.xml
docker exec backend-portfolio-backend-1 python -m app.cli.ingest_flex_xml /tmp/stmt.xml --dry-run
docker exec backend-portfolio-backend-1 python -m app.cli.ingest_flex_xml /tmp/stmt.xml
```

`app/cli/ingest_flex_xml.py` reuses `IBKRService.parse_flex_xml()` and
`sync_helper.ingest_flex_statement()` — the *same* functions `POST /api/sync/ibkr` and the scheduled jobs
use — so reconciliation order, the empty-statement wipe guard and the idempotent upserts all apply
identically. It records a `sync_runs` row with `sync_type='ibkr_manual_xml'`. Touches no network at all
(no Flex, no Yahoo). `--dry-run` reports counts without writing. Tests: `tests/test_manual_xml_ingest.py`.

There is deliberately **no upload endpoint**: `/api/` is proxied publicly, and a route that rewrites tax
lots is a far larger surface than a CLI run over ssh — write auth (below) narrows that surface but does
not change the judgement.

### Offline price import — the escape hatch from a wrong or missing feed

`app/cli/import_prices.py` is the price-side twin, for when Yahoo can't be called (rule 1) or can't
resolve a listing at all. It takes a JSON file of daily closes and writes them through the same
`MarketPriceRepository.bulk_create()` upsert the sync uses, so it is re-runnable and a later Yahoo
fetch overwrites cleanly. Records `sync_type='manual_prices'`. Touches no network.

```bash
docker cp prices.json backend-portfolio-backend-1:/tmp/prices.json
docker exec backend-portfolio-backend-1 python -m app.cli.import_prices /tmp/prices.json --dry-run
docker exec backend-portfolio-backend-1 python -m app.cli.import_prices /tmp/prices.json
```

```json
{"symbol": "SBI", "exchange": "TSE", "currency": "CAD", "source": "ibkr",
 "prices": [{"date": "2026-07-27", "close": 4.79}]}
```

**IBKR's Client Portal is the good source for this** (`get_price_history` via the MCP connector):
independent of Flex, so it spends no token budget and can't trip `1025`, and it quotes the listing's
own currency. That's how SBI was refilled — 2 years of daily CAD bars, `source='ibkr'`.

A **currency mismatch against the security refuses the whole file**, mirroring the guard on Yahoo
auto-discovery, because writing USD closes under a CAD security is the exact bug this CLI repairs.
A malformed row also rejects the whole file: a partially-applied series is indistinguishable
afterwards from a complete one. Ambiguous `symbol` (ASML is two rows) refuses rather than guessing —
pass `--security-id`. Tests: `tests/test_price_import_cli.py`.

Note the trade-off: once a date has a price, `get_missing_dates()` never re-fetches it, so an
imported window stays imported (visible in `market_prices.source`) until something deletes it.

### `_sanitize_flex_xml()` — why it exists

ibflex 0.15 (released 2021) converts **every** XML attribute onto a frozen dataclass and raises
`FlexParserError` on the first thing it can't handle, which **aborts the entire document** — so one
unrecognised field kills the whole sync, open positions included. IBKR has drifted well past it:

- **Unknown attribute names**, e.g. `subCategory` on `<Trade>` (modelled only on `SecurityInfo`).
- **Unknown enum values**, e.g. `type="Broker Fees"` — the query can enable 17 cash-transaction types
  but `enums.CashAction` models 10. Also `CorporateAction.type` (`Reorg`) and `notes`/`code` (`Code`).

`IBKRService._sanitize_flex_xml()` runs before `parser.parse()` and:
1. drops **any attribute ibflex's own `parser.parse_element_attr()` rejects** — that single call covers
   unknown names, bad enum values, unparseable dates/decimals and unknown currencies, and can't drift
   out of step with ibflex;
2. drops aggregate duplicate rows (`levelOfDetail` in ORDER / SYMBOL_SUMMARY / CLOSED_LOT / …) when
   real execution rows sit beside them, since IBKR gives each its own `transactionID` and ingesting
   both would **double-count trades and realized P&L** — but keeps them if they're all there is, so a
   populated section is never emptied.

It returns the original bytes untouched when nothing changed, never raises, and reports every drop via
`warnings[]` (surfaced in the sync response). **Don't patch attribute names one by one** — it's generic.
`_fix_currency_codes()` still runs first so `RUS`→`RUB` is repaired rather than dropped.

Degradation is graceful: an unknown cash `type` becomes `None` and the row is skipped by
`extract_cash_transactions` (which only wants dividends/withholding); an unknown reorg `type` lands as
`'UNKNOWN'` with quantity and date intact.

Tests: `tests/test_flex_xml_sanitizer.py`, `tests/test_flex_ingestion_e2e.py`.

---

## Database schema

- **securities** — composite identity `isin + exchange` (same stock on two exchanges = two rows, e.g.
  ASML on NASDAQ *and* AEB). Also `symbol`, `description`, `currency`, `conid`.
- **taxlots** — one row per purchase: `open_date`, `quantity`, `cost_basis`, `cost_basis_eur`
  (pre-converted), `is_open`, `close_date`, **`close_source`** ∈ `trade` | `corporate_action` |
  `heuristic`.
- **trades** — authoritative executions, idempotent on `ib_key`: `buy_sell`, `quantity`, `price`,
  `proceeds`, `commission`, **`realized_pnl`** (IBKR's own FIFO). `security_id` is nullable — a fully
  sold security is no longer in OpenPositions.
- **corporate_actions** — `action_type` (Reorg name), `quantity`, `value`, `proceeds`, `description`.
- **cash_flows** — external cash, idempotent on `ib_key`: `flow_date`, **`flow_type`** ∈
  `DEPOSITWITHDRAW` | `TRANSFER_IN` | `TRANSFER_OUT` | `TRANSFER`, `amount` (signed as IBKR reports:
  deposit +, withdrawal −), `amount_eur` (pre-converted at `flow_date`). Only `DEPOSITWITHDRAW` counts as
  money added — see the contributions section.
- **dividend_payments** — `gross_amount_eur`, **`withholding_tax_eur`**, **`net_amount_eur`**,
  `pay_date`, **`source`** ∈ `ibkr` | `yfinance_estimate`.
- **exchange_rates** / **market_prices** — caches. **ticker_mappings** — IBKR→Yahoo symbols.
- **app_settings** — `base_currency`, `last_sync_to_date`. Plus fundamentals + earnings tables.
- **sync_runs** — one row per sync attempt (`sync_type` ∈ `ibkr` | `ibkr_sync` | `full_sync` |
  `market_data_only` | `ibkr_manual_xml` | `manual_prices` | `manual_mapping` | `manual_cash_flow` |
  `manual_dividend_prune` | `manual_dividend_purge`,
  `status`, `message`,
  `details`, `warnings`). Timestamps are
  serialized UTC-aware via `utc_iso()` — a bare naive `isoformat()` is parsed as *local* by the browser,
  which once made an 08:00 sync display as 06:02.
  `SchedulerService.last_sync_result` is in-memory only and auto-deploy restarts on every push, so
  without this the daily validator can't tell "no sync ran" from "the container restarted".
  `/api/scheduler/status` falls back to it; `/api/scheduler/history?limit=N` lists recent runs.
  Recording is best-effort — it must never fail a sync or mask the real error.

**Every stored timestamp is a naive UTC datetime, and `app/clock.py` is the only way to make one.**
The columns default to `func.now()`, which SQLite answers in UTC, and `utc_iso()` serializes by
stamping UTC onto a value it *assumes* is already UTC. The stdlib's argument-less `now()` returns naive
**local** time, so it was correct at ~49 call sites only because `python:3.11-slim` sets no `TZ` — an
undeclared dependency on the base image that nothing would have noticed breaking. Off the container it
was already wrong three ways at once: cache cutoffs (`now - timedelta(days=7)` against a naive-UTC
column) expired an offset early, ages (`now - row.last_synced`) read an offset too old, and
`utc_iso(datetime.now())` labelled local time as UTC so the browser converted it a second time — the
"two clocks on one line" failure `utc_iso` exists to prevent, reintroduced through its own argument.
`utcnow()` stays **naive** on purpose: these values are compared against naive columns, where an aware
value raises `TypeError` rather than degrading. `tests/test_clock_convention.py` walks the source tree
so the old call cannot return, and asserts against real UTC rather than local — the assertion that
passes vacuously on the container and catches the bug everywhere else.

Migrations: `cd backend && alembic upgrade head` (the container CMD runs this on every start).

---

## Reconciliation & realized P&L

`reconcile_taxlots()` (`sync_helper.py`) explains quantity changes in priority order:
1. **SELL trades** → close lots FIFO with the real date/proceeds/`fifoPnlRealized`; `close_source='trade'`
2. **Corporate actions** → deterministic reclassification (split/spinoff/merger), not a sale
3. **Fallback heuristic** (quantity drop + `COST_CONSERVED_RATIO`) → `close_source='heuristic'`

**That order is the code's order, and it wasn't until 2026-07-30.** The trade lookup used to run
*third*, supplying only a date and a provenance tag after 2 and 3 had already decided — so a trim of
**≤1% of cost basis** took the cost-conserved path and recorded **no closure at all** while IBKR's own
SELL sat in `trades` for that window (200 shares at 20,000 sold down by 2 leaves 19,800, and
`19800 >= 20000 * 0.99`). The disposal then never reached `calculate_xirr()`'s `+proceeds` inflow, the
attribution's disposal term, that day's `external_flow_eur`, or the tax report's `closed_lot_estimate`.
The two inferences now run **only when no SELL is on record**, so the reverse-split and cash-in-lieu
protections are untouched — pinned from both sides in `tests/test_sync_helper.py`.

**`open_date` comes off `position.openDateTime`, parsed by ibflex.** It used to be scraped from the raw
XML into a separate list and matched back by position index, but that list kept only STK rows carrying
the attribute while the loop enumerated *every* `OpenPosition` — so one bond/option row, or one lot
without the attribute, shifted every index after it, and the `conid` check fell back to `reportDate`
rather than realigning. One stray row silently stamped **every later lot** with the statement date.
ibflex 0.15 does parse the field (`parse_element_attr` returns a `datetime`); the comment claiming
otherwise was wrong. Don't reintroduce index matching. Tests: `tests/test_ibkr_parsers.py`.

`restamp_unsourced_closed_lots()` then fixes lots closed *before* `<Trades>` existed: those carry the
date the sync **noticed** the drop, not the sale date (CRM and NFLX read 2026-04-17 for a 2026-03-13
sale). A lot is only re-stamped when exactly one SELL for that security matches its quantity and isn't
newer than the recorded close date — ambiguity is left alone rather than guessed. Idempotent (a stamped
lot has a `close_source`), so it self-disables.

Note `conid_to_security_id` is built from the statement's **OpenPositions**, so a security sold out
entirely isn't in it; `persist_transactions` falls back to a DB lookup by conid, otherwise every SELL
trade lands with `security_id = NULL`.

**Empty-statement wipe guard:** if incoming tax lots are empty but the DB holds open lots, the sync
**aborts** instead of marking everything sold. A successful-but-empty statement is treated as a failure.
This guard has already saved the data through several failed syncs.

`get_realized_totals()` prefers `trades` (exact) and falls back to a market-price approximation over
closed lots. `realized_rows_from_closed_lots()` is **shared** by the portfolio totals and the tax report
so the two can never disagree — they did once, and that was a bug. The picker keys on **SELL trades
specifically**, not on the table being non-empty: a BUY-only statement returned hard zeros and
permanently suppressed the fallback, while the tax report (which decides per year) still showed real
gains. Pinned by `tests/test_realized_totals.py`.

**A lot sold on D is not held at D's close.** One convention, everywhere: `_calculate_daily_value`,
`holdings_snapshot_as_of()` and the attribution gates all exclude **on** the close date, matching what
the benchmark always did. Under the old include-on-close rule a same-day rotation double-counted that
day (the sold lot still "active" beside its replacement) and a position sold on 31 December landed in
both the year's Steuerwert *and* its realized gains. Consequence to expect: a sale's value leaves the
chart on the sale date itself, one day earlier than before. The disposal windows in `calculate_xirr()`
and the attribution endpoint are therefore `(start, end]` — a lot sold *on* the window end yields
proceeds precisely because the end valuation no longer carries it. Change these together.
Tests: `tests/test_close_date_boundary.py`.

**Realized proceeds are inflows, not absences.** `calculate_xirr()` books each lot closed in the window
as a `+proceeds` flow (plus net dividends, era-spliced) alongside the `−cost` of lots opened. Without
that, selling A to buy B added a fresh outflow with no matching inflow, so every rotation crushed the
reported return — the planned IE→US ETF switch would have roughly halved it. Its guard is a
**sign change**, not `start_mv > 0 and end_mv > 0`: a window may legitimately start at zero (before the
first purchase) or end at zero (fully liquidated, where the proceeds carry the whole return). Windows
under 30 days return `method="simple_period"` and the UI labels that tile *Period Return* rather than
annualizing a few days of noise. Attribution takes the same disposal term
(`pnl = value_change + disposals − new_investment`), without which a position sold at a profit read as
`−start_value`. Tests: `tests/test_xirr.py`, `tests/test_attribution.py`.

**The timeline is swept once, not rebuilt per day.** `_calculate_timeline_swept()` folds each lot's
date-independent parts (base-converted cost at `open_date`, quantity) into running sums via open/close
events, so a day prices each *security* once instead of once per lot — O(days × securities) rather than
O(days × lots) with a 15-probe price walk inside. `_calculate_daily_value()` remains for point queries.
The two are numerically identical by construction and pinned that way
(`tests/test_timeline_equivalence.py` asserts exact equality across closed lots, a same-day rotation,
price gaps, a USD security and a CHF base) — **keep them in lockstep**.

**A split also invalidates the cached prices.** Yahoo restates historical `Close` after a split, but
`get_missing_dates()` only fetches dates we *don't* have, so pre-split rows are never refreshed while
IBKR restates the lot quantity immediately — leaving a step change in the chart that nothing detects.
So `invalidate_prices_for_splits()` deletes `market_prices` up to and including the action date
(`MarketPriceRepository.delete_up_to`), and the next market-data sync refetches them — one extra
request per security, since fetching is range-based.

**Holidays are not "missing" forever.** `get_missing_dates()` skipped weekends but not market holidays,
so a date the exchange never traded (4 July, Good Friday) stayed missing permanently — and one such date
makes `fetch_and_cache_prices` re-request that security's **entire range** on every one of the five
daily jobs, indefinitely, against an IP-based rate limit. An **interior** weekday hole (cached data on
both sides) older than `HOLIDAY_GRACE_DAYS` (30) now counts as a holiday: every sync since has already
failed to fill it. Younger holes stay missing so late data can arrive, and **leading/trailing gaps stay
missing at any age** — which is exactly what a purge-and-refill repair looks like, so `--purge-prices`
and the split invalidation above still heal normally. `BenchmarkService` applies the same rule via its
own `_missing_business_days()`, shared by its price *and* FX paths. Tests:
`tests/test_missing_dates_holidays.py`, `tests/test_benchmark_fx_window.py`.

The fetch is also **span-narrowed**: the Yahoo request starts a few days before `min(missing)`
(`PRICE_FETCH_BUFFER_DAYS`), not at the window start — the 08:00 730-day job used to re-download two
years per security every morning purely because today's close hadn't published (~19.5k rows rewritten
to gain a few hundred). A split purge or a newly added security still pulls the whole span, because
that is where `min(missing)` then sits.

Two details carry the weight. `PRICE_RESTATING_ACTIONS` is a deliberate **subset** of
`SPLIT_LIKE_ACTIONS`: we fetch with `auto_adjust=False` and Yahoo rebases raw `Close` for splits only,
so `SPINOFF`/`STOCKDIV`/`ISSUECHANGE` are excluded as pure churn. And it fires **only for actions
newly inserted on this sync** (`CorporateActionRepository.existing_ib_keys()`) — the statement
resends every action inside its period every time, so without that check all five daily jobs would wipe and refetch the
same history forever. Reported in `warnings[]` and as `prices_invalidated`.
Limitation: the 7-day jobs restore the current value, but the full history only comes back at the next
**08:00** 730-day `full_sync`. Tests: `tests/test_split_price_invalidation.py`.

---

## Tax report (Swiss framing)

`GET /api/tax/report?year=YYYY` and `.csv`. Switzerland doesn't tax private capital gains but does tax
dividend income and allows reclaiming foreign withholding via **DA-1** — so the report leads with
dividend income + withholding, then realized gains, then a year-end holdings snapshot (Steuerwert).

Two honesty flags, both badged in the UI and CSV:
- `dividend_source`: `ibkr` (real withholding) vs `yfinance_estimate` (gross guess, no withholding)
  vs `mixed` (the boundary year). Dividends are **era-spliced with the same `_splice_by_era` the
  card uses** — estimates strictly before the globally first IBKR payment (`dividend_ibkr_from`),
  IBKR rows from there on — then windowed to the year. Both simpler schemes were bugs: a global
  "prefer ibkr" made 2025 report **0.00 labelled authoritative**, and a per-year boolean dropped
  the boundary year's real January income (the ledger starts mid-February). A per-year *boundary*
  would be wrong too — yfinance stores a dividend under its ex-date, IBKR under its pay date, so
  it would resurrect the double-count. The two sources are never summed for the same period; each
  income row carries its `source`.
- `realized_source`: `trades` (IBKR FIFO) vs `closed_lot_estimate` (market price at close date — was
  ~8% off on a spot check, hence the badge)

**Steuerwert is valued at 31 December**, not today: `holdings_snapshot_as_of()` rebuilds the holdings
for `holdings_as_of` (= 31 Dec for a past year, today for the current one) using the same
`open_date`/`close_date` window as `_calculate_daily_value`, so it can't disagree with the portfolio
timeline. Positions with no resolvable price near that date are **omitted**, not counted as zero.

**A figure this report cannot justify is absent, not invented** (both halves were bugs until
2026-07-30, and both broke the rule the rest of the codebase follows: skip the row, log it, report it).

- `_to_eur()` returned the **unconverted foreign amount** when FX failed, so a TWD sale whose
  trade-date rate fell outside `FALLBACK_MAX_AGE_DAYS` read ~35× high while `realized_source` still
  said `trades` — the badge that means *authoritative* — with no `logger` call anywhere on the path. It
  returns `None` now and the realized loop omits the row. If **every** SELL is unconvertible the
  closed-lot approximation takes over (it reads `cost_basis_eur`, converted at ingest, so it needs no
  trade-date rate) and the warning says *that* rather than claiming a hole.
- An `except Exception: pass` turned any snapshot failure into a Steuerwert of **0.00**, served 200
  with the note still claiming the holdings were valued at that date's closes. `holdings_snapshot_total`
  is now **`None`** on failure — a missing wealth-tax base, not a zero one — alongside
  `holdings_snapshot_error`, and the note says so.

`warnings[]` on the report is the surface for both. It rides on a **successful** response, so it is
structurally invisible unless rendered: `TaxTab` shows it as a banner and `to_csv()` writes a WARNINGS
block. Tests: `tests/test_tax_service.py`, plus the shape assertions in `tests/test_api_smoke.py`.

Frontend: `TaxTab.tsx`. It's a filing aid, not tax advice.

---

## Dividends — history and forecast

`GET /api/dividends/breakdown?year=&forecast=` → `DividendService.get_dividend_breakdown()`, rendered by
`DividendsTab.tsx`: net dividends by month **stacked by symbol**, a year filter (All time + the years
with data), a Forecast toggle, and a per-stock table (payouts, net, projected, trailing-12M yield).
Unlike `/summary` it **never enqueues a sync**, so it cannot reach Yahoo (rule 1) — everything comes
from `dividend_payments`, `taxlots`, `market_prices` and `exchange_rates`.

**The two sources are era-spliced, never mixed or dropped.** `_splice_by_era()` keeps
`yfinance_estimate` rows strictly *before* the first IBKR payment date and IBKR rows from there on.
`get_dividend_summary()` used to call `has_ibkr_dividends()` **unwindowed** and then filter to
`source='ibkr'`, so the moment July 2026's real rows landed, every pre-IBKR month vanished from the
card — the repository's own docstring warns against exactly that. The boundary is reported as
`ibkr_from`.

**`get_dividend_summary()` returns NET, and its `source` is three-way.** Both were wrong on the
Performance tab's *Dividend Income* card until 2026-07-30: the service annotates its own return
`# NET per month`, but the card said "Gross dividend income by month" and footnoted "Estimated gross
dividends via Yahoo Finance — withholding taxes … not reflected" over IBKR actuals net of real tax, so
it silently disagreed with the Dividends tab and anyone reconciling DA-1 read net income as pre-tax.
`total_gross_eur` / `total_withholding_eur` / `source` / `ibkr_from` were already on the wire and simply
undeclared in `DividendSummaryResponse`. `source` was also binary — `'ibkr'` the moment any IBKR row
existed, while the splice still carries the estimated months ahead of the boundary — and is now the
same `ibkr` | `mixed` | `yfinance_estimate` flag the tax report uses (`_summary_source()`), which the
footnote reads off. `/api/dividends/summary` now carries a `response_model`, but **completing the
model had to come first, and that order is the whole point**: a `response_model` is a *filter*, so
attaching one to a model still declaring five of the ten keys would have deleted the provenance
fields from the wire and blanked the footnote — shipping the exact bug as a hardening change. For
that reason `tests/test_dividend_summary_contract.py` compares the service's key set against the
model's in both directions rather than spot-checking names: an undeclared key is dropped silently,
and a declared-but-unsupplied one silently takes its default (0.00 withholding, estimate
provenance). Add a key to the service and you must add it to the model.

**Only dividends that could have been earned are ingested.** `sync_dividend_data()` skips ex-dates
before the security's earliest lot `open_date` (reported as `pre_ownership_skipped`); a security with no
lots yet keeps its whole history, since there is no cutoff to infer. Before that, yfinance's full
history meant **1355 of 1446 rows** on this account were zero rows reaching back to 1985 — the reason
the card once reported 439 months, and the reason relaxing one read-side filter broke
`/api/dividends/breakdown` outright. Both readers still filter via `DividendService._is_income()`
(gross **or** net positive) and `_net_eur()` falls back to gross for rows predating the
withholding-fields migration, which carry a NULL net — **use those two helpers rather than touching
the columns directly.** Existing junk is removable with `app/cli/prune_empty_dividends.py --dry-run`.
Run on prod 2026-07-29 (`manual_dividend_prune`): 1350 zero rows removed, real payments remain.

**"Carries no income" is not sufficient grounds to delete a row, and treating it as such was a bug
(fixed 2026-07-31).** The forecast infers cadence from the **raw** history — see *Size from
`amount_per_share`, not from income received* below — so a pre-ownership yfinance row is
simultaneously income-free and load-bearing: it is exactly what lets a recently-bought payer project
at all. The old predicate deleted precisely those, silently reverting the "20 payers project" fix
toward the old 15, and the CLI's own docstring claimed it "deletes only rows the readers already
ignore" — true when written, false once the forecast became a reader of them. Prune is now
additionally bounded by **the ingest window it should always have mirrored**: a row goes only when it
is older than `PRE_OWNERSHIP_HISTORY_YEARS` before the security's first lot, i.e. exactly what
`sync_dividend_data` would no longer create. A security with **no lots** is left entirely alone,
matching ingest's own refusal to guess a cutoff. Rows awaiting computation
(`shares_held IS NULL`) are still never touched. Tests:
`tests/test_prune_preserves_forecast_basis.py`.

### A wrong mapping poisons dividends too, and only prices were ever purged

`dividend_payments` rows tagged `yfinance_estimate` are keyed to whatever Yahoo ticker resolved when they
were written. Correcting a mapping does not retire them, and until 2026-07-30 nothing could:
`manage_mappings disable --purge-prices` cleared `market_prices` only, `DividendRepository` had no delete
method at all, and `prune_empty_dividends` never deletes a row carrying income — so a poisoned row
with a plausible positive amount was unreachable by every tool.

That is the second half of the SBI failure. `SBI@TSE` is **SERABI GOLD PLC** (CAD, Toronto). The mapping
was corrected to `SBI.TO` and the prices purged and refetched on 2026-07-27; its two dividend rows,
computed 06-24 and 07-25 under the bare-ticker US listing, survived. Because cadence comes from whichever
series carries `amount_per_share` — and skips the IBKR rows when one exists — **those two rows alone
projected five monthly payouts for a company that does not pay monthly, while its one real payment was
discarded.** Realized income stayed correct throughout, since the era splice drops estimates after
`ibkr_from`; the damage was confined to the forecast, which is why it survived a month unnoticed.

Three things close it:

- **`app/cli/purge_dividend_estimates.py`** — deletes a security's estimates, never an `ibkr` row (those
  carry real withholding and no mapping can invalidate them). `--dry-run`, ambiguous symbols refused,
  records `manual_dividend_purge`. Run on prod 2026-07-30: 2 rows, income unchanged to the cent, forecast
  went 5 payouts → 0. **Nothing projected is the correct outcome** until a genuine series exists.
- **`disable --purge-prices` now purges estimates too**, and `set` warns when a ticker change makes
  existing estimates suspect. `list` flags `DIVIDENDS PREDATE MAPPING`.
- **`find_dividends_predating_their_mapping()`** runs after every market-data sync, warning when a held
  security's estimates were computed before its mapping's `updated_at`. That comparison is why
  `ticker_mappings` gained `created_at`/`updated_at` — it had **no timestamps at all**, which is what made
  "did this data come from the current ticker?" unanswerable for months.

The identity is `(security_id, source, ex_date)`, not `(security_id, ex_date)`: the column holds an
ex-date for yfinance rows and the **pay** date for IBKR ones, and one shared slot let them overwrite each
other whenever a payer's lag landed on another record's date — producing a single row with IBKR's gross
and the estimate's per-share. Mastercard's 29-day lag already exceeds a monthly cycle. The downgrade in
`o8d5f2a9b3c4` refuses (before any DDL) when cross-source same-day rows exist, because re-narrowing a key
over data the wider one allowed is lossy.

### The forecast — four rules that were each a bug first

**Size from `amount_per_share`, not from income received.** The payout schedule belongs to the company,
not to how long we have held it. Keying on realized income meant a payer bought weeks ago looked like a
non-payer, and **only 15 of 36 held securities could be forecast** — TSMC, Samsung, SK Hynix, HPE and the
**SOXQ ETF** each had 20–59 per-share records and projected nothing. Now 20 payers project.

**Infer cadence from ONE dated series.** The same dividend is stored twice — yfinance under its ex-date,
IBKR under its pay date, weeks apart — which halves the apparent gap: ASML's quarterly schedule read as
74 days, 5 payouts a year instead of 4. Deduplication cannot fix it, because Mastercard's ex-to-pay lag
of 29 days exceeds a monthly payer's whole cycle. Where yfinance rows exist (`amount_per_share is not
null`, ≥2 of them) they alone define the schedule; IBKR rows still supply the net amounts.

**The cost of that rule, and the guards added 2026-07-30:** the chosen series is trusted absolutely,
*including over the IBKR rows it then discards*. So two bad estimate rows can define a schedule outright
— which is exactly what SBI did (see *A wrong mapping poisons dividends too* below). The rule stays,
because the alternative resurrects the double-count; what changed is that a thin or suspect inference now
declares itself. `forecast_samples` and `forecast_cadence_days` ride on each breakdown row (badged at
n≤2), and `find_dividends_predating_their_mapping()` warns when the rows came from an older ticker.
**Earlier revisions of this file cited "SBI's monthly read as 28 days" as an example here. That was the
poisoned data, not a real schedule — don't reinstate it.**

**Step by the calendar.** Dividends pay on a day of the month, so a fixed day-step drifts — 31 days gives
a monthly payer 11 payouts a year instead of 12, and 91 days walked a quarterly payer from the 15th to
the 14th to the 13th. A gap near a calendar period snaps to it (`CALENDAR_PERIODS`), keeping the
schedule's own day and clamping at month end; anything else keeps day-stepping.

**Judge staleness from *now*, not from the horizon.** The stopped-payer guard compares against `as_of`,
because the distance to a future horizon is a property of the question. Otherwise asking about 2027 made
every payer look stopped and returned an empty year.

`forecast_basis` reports which amount was used: `net` when a dividend has actually been received (net of
withholding), `gross_estimate` when only yfinance's gross per-share exists — the latter runs a little
high and the UI badges it. Future years are selectable (`years` offers `as_of.year + 1`) and a future
year is forecast in full rather than from today.

**Accumulating ETFs correctly show nothing** — DBPG, EMIM, IWDA, SXR8, VWCE, XAIX, XNAS (the `1C`/`ACC`
suffixes), alongside genuine non-payers (AMD, Amazon, Arista, NU, Credo, Ondas). Verified rather than
assumed: each has 600+ cached prices, so the Yahoo ticker resolves and the empty dividend series is real.
**Don't "fix" their absence.**

**Forecasts are inferred, because nothing forward-looking is cached** — no announced dividends
anywhere, and the fundamentals/earnings tables carry no dividend fields. `dividend_forecast.py` is a
pure module (no DB, no network, fast unit tests): cadence is the **median gap** between recent
payments, the amount the **median** of recent payments scaled to the current holding — median so one
special dividend doesn't inflate every projection. It refuses rather than guesses: nothing held, fewer
than two payments, a gap outside 20–400 days, or a payer that has already skipped ~2.5 cycles all
project nothing. IBKR rows carry no `amount_per_share` and a `0` `shares_held` sentinel, so the
scaling falls back to shares held at the pay date, then to the unscaled amount.
Tests: `tests/test_dividend_forecast.py`, `tests/test_dividend_breakdown.py`.

**One projection pass, sliced per consumer.** `_forecast_inputs()` assembles the cadence/per-share
inputs once, and `project_dividends()` then runs a single wide horizon (to the end of *next* calendar
year) which each reader filters: the chart, the rolling next-12-months figure, and the per-year
comparison. This is safe only because the projection steps deterministically from the last known
payment, so a wide projection sliced to a window equals projecting that window directly.
**The chart's reach is deliberately narrower than the projection's** — without a selected year it
still stops at 31 December. Coupling the two tripled the all-time chart's forecast total (46 → 162)
by pulling next year's payments into it.

### Growth — MoM / YoY, and the five ways it lies

`growth` and `upcoming` on `/api/dividends/breakdown`, rendered as the KPI strip, the per-year panel
and the calendar (`DividendKpiCards`, `DividendYearComparison`, `DividendCalendar`, `DeltaChip`).

Computed from the **unwindowed** history, deliberately: with `?year=2026` the response carries no
2025 months, so no client could derive year-over-year at all. It is byte-identical whichever year is
selected, and pinned that way. Keeping it server-side also keeps the era splice and the per-date FX
projection in one place instead of growing a second implementation to drift.

**Rolling 12 months leads; raw MoM cannot.** This account's payers are quarterly, so March pays and
April does not: month-over-month swings ±90% on cadence alone and says nothing about the portfolio.
MoM survives as a labelled figure on the latest realized month and in the chart tooltip.

Each of these was a wrong number before it was a rule:

1. **YTD is compared day-for-day.** Jan 1 → today against Jan 1 → *the same calendar day* last year.
   Measuring a part year against a whole prior year turned +527% into +99%. 29 February has no
   counterpart, so `_same_day_last_year()` falls back to the 28th.
2. **The first year of income is coverage-limited.** It starts whenever the first dividend landed, not
   in January — seven months here — so its successor's percentage overstates growth and carries
   `yoy_vs_partial` (badged `†`). The first year itself gets no percentage.
3. **The TTM comparison straddles the era splice.** The current 12 months are IBKR actuals while the
   prior 12 are yfinance estimates: comparable in size, not in provenance. `ttm_crosses_era` says so
   rather than presenting a change of source as growth.
4. **Forecast is never silently compared against measured.** `next_12m_vs_ttm_pct` and any annual row
   containing projection are marked `est.`.
5. **A zero base yields `null`, never a percentage.** Growth against zero is undefined, not large, and
   a quarterly payer produces zero months constantly. `_pct()` returns None and the UI renders a dash.
   Per-month growth is realized-only for the same reason — a projected month's "change" would be an
   artifact of the forecast's own flat median.

The per-year panel is the one surface that mixes measured and projected into a single bar, so with the
Forecast toggle **off** it rebuilds from realized income alone (`lib/dividendGrowth.ts`), which is the
only client-side growth arithmetic and copies the server's two rules exactly: adjacent years only,
never divide by zero. Tests: `tests/test_dividend_growth.py`, `src/lib/dividendGrowth.test.ts`,
`src/lib/delta.test.ts`.

---

## Contributions — money in per month

`GET /api/portfolio/contributions` → `PortfolioService.get_contributions()`, rendered as a slim strip
(`ContributionsStrip.tsx`) below the KPI cards: all time / 12M / 6M / 3M, each trailing window shown as
a delta against the all-time average, so a change in savings rate is visible at a glance.

**`money_in_eur` is the answer**, and it is **spliced at `coverage_from`** because no single source is
authoritative for the whole history. This design took three attempts; the reasoning below is why.

### The splice

| Era | Source |
|---|---|
| before `coverage_from` | **lot cost basis** (`Σ cost_basis_eur` of lots opened) |
| from `coverage_from` | **real deposits** (`cash_flows`, `DEPOSITWITHDRAW` only) |

`money_in_method` reports which applied: `deposits` \| `spliced` \| `deployed`.

Lot cost basis reaches back through the pre-IBKR years because the early-2026 portfolio transfer from
Scalable Capital and Trading 212 carried every lot across with its **original `openDateTime` and original
cost basis** — verified, not assumed: securities have as many distinct `costBasisPrice` values as they
have lots (DBPG 75 lots / 72 prices, XNAS 110/107, XAIX 54/54), which a transfer-date re-basing could not
produce. Lots then survive indefinitely because reconciliation deletes **open** lots only and splits a
partial sale **pro-rata** under the original `open_date`.

Deposits take over the moment a ledger exists, because **lot cost basis cannot survive a rotation**:
selling one ETF to buy another closes lots and opens new ones for the same money, so it is counted twice.
That is not hypothetical — the Ireland-domiciled sleeve is being switched to US-domiciled ETFs for tax
reasons. Simulated on the real lot set (every EUR lot rotated into a USD one, no new cash), `money_in`
held **exactly flat in all four windows** while deployment roughly **doubled** all-time and went up
**~4x** over 3M — the shorter the window, the worse the distortion, because the rotation fills more of
it. A deployment-led headline would have claimed four times the real 3-month contribution. Pinned by
`test_a_rotation_does_not_inflate_money_in`.

**No double-count at the boundary**, because it is a single date: lots are summed strictly `< coverage_from`
and deposits strictly `>= coverage_from`. A purchase funded by a deposit in the boundary month contributes
the deposit only. The two ranges also leave no hole, which is why the divisor is the window's **full**
elapsed months and every window carries a meaningful number.

`coverage_from` lives in `app_settings` (`cash_flows_covered_from`), set from the statement's `from_date`
and **only when deposit rows were actually present** — an export taken without the Deposits option must
not claim coverage it has no data for. It only ever widens backwards
(`widen_cash_flows_covered_from`), so neither a later statement nor the 2026-07-31 switch to a
30-day window can shrink what a prior-year import established — the narrower `from_date` is simply
ignored, which is what kept `coverage_from` at 2026-01-09 through that change. It must be the period start, not the first deposit's date: a covered week with no deposits is
still covered, and using the first row would hand that week's purchases to the lot side *and* count its
deposits.

**But the period start is a claim, not evidence, and `get_contributions()` clamps it forward to
`CashFlowRepository.earliest_flow_date()`** — the first row the ledger holds, of *any* type. **The account
is younger than the statement that reports it**: a YTD query in the first year begins on 1 January while
the account was funded weeks later, and in that gap the deposits table is empty because the money was
still going to the previous broker. Believing the claim drops those purchases from **both** sides — past
the lot cutoff, with no deposit standing in for them — so they vanish from money in with nothing
reporting it. Clamping hands the gap back to lot cost basis, which is the right source for any era the
ledger doesn't reach.

Two details. It keys on the earliest row of **any** type, not the earliest deposit: an account opened by
an in-kind transfer can trade before any cash is deposited, and anchoring on the first deposit would
leave that window on the lot side where a rotation inflates it. A transfer is never money in, but it *is*
evidence the account existed. And the clamp is applied at **read** time rather than stored, so it needs no
migration, a later YTD sync can't undo it, and a prior-year import — planned for the 2025 tax backfill —
can't silently move the boundary back into an era the ledger has nothing for.

Do **not** "simplify" this by splicing at the transfer date instead. Deposits into the new account
routinely start *before* the positions arrive, and those deposits fund purchases made after it; a
transfer-date boundary drops them from the deposit side while their lots sit past the lot cutoff. On this
account that is the larger error of the two. Tests:
`test_coverage_cannot_start_before_the_ledger_has_any_row`,
`test_a_transfer_row_alone_anchors_the_ledger_start`.

### `deployed_eur` — secondary, and deliberately still shown

Cost basis of lots opened, the old headline. Once rotation starts it exceeds `money_in_eur`, and **that gap
is the useful part**: it is capital churn, not saving.

**Do not promote it back, and do not "fix" it by averaging `net_eur` instead.** Both were tried. Averaging
net moves the error rather than removing it — a window then gets debited for a sale of something bought
*before* it began. The two are duals; `net_eur` survives only for the tooltip and the identity check.

### Transfers are never money in

An incoming transfer moves capital saved years earlier somewhere else, and the transferred lots already
carry their own `open_date` — so counting it would both invent savings in a month that had none *and*
double-count purchases already recorded. `CashFlowRepository.get_deposits()` therefore selects
`flow_type == DEPOSITWITHDRAW` by **whitelist**, so no new transfer-ish type can leak in.

IBKR may book a transfer's cash leg as an ordinary "Deposits & Withdrawals" row. `persist_cash_flows()`
catches that by matching `(flow_date, amount, currency)` against the `<Transfers>` rows — exactly, never
on description text — and reclassifies, reporting it in `warnings[]`. Zero-cash (in-kind) transfers are
left out of the match keys, or every no-cash transfer would collide on `(date, 0)`.

**This is the highest-risk number in the feature**: an unexcluded transfer shows a portfolio-sized fake
contribution. `app/cli/manage_cash_flows.py` is the manual override — `list` marks which rows count as
added, `reclassify <ib_key> --as TRANSFER_IN` fixes one, `--dry-run` on the mutating path, and every
edit records a `sync_runs` row (`manual_cash_flow`).

Three things this account's real data settled, so nobody re-investigates them:

- **The 2026 transfer was entirely in-kind** — all 22 rows carry `cashTransfer=0`. So there is no
  transfer cash to misclassify and `deposits_reclassified_as_transfer` is legitimately **0**. Read a zero
  there as correct, not as the guard failing to fire.
- **`Transfer.type` arrives as `FOP`** (Free Of Payment), which ibflex's `TransferType` enum
  (`INTERNAL`/`ACATS`) cannot convert, so the sanitizer drops it and `transfer_type` is always
  `'UNKNOWN'` here. `_transfer_to_flow` leaves `UNKNOWN` out of the description. **Do not extend the
  enum** — same reasoning as everywhere else in the sanitizer.
- **`deliveringBroker` is not modelled by ibflex** either, and `company` comes through empty, so a
  transfer row cannot name Scalable Capital / Trading 212. `direction` *does* survive, which is what
  `TRANSFER_IN` and `earliest_transfer_in_date()` depend on.

### Currency

Every amount is stored EUR-converted at its own date (`cash_flows.amount_eur` via
`convert_to_eur(amount, currency, flow_date)`, `taxlots.cost_basis_eur` at `open_date`) and projected into
the base currency once at read time by `BaseFx` — deployment at each lot's `open_date`, deposits at each
flow's `flow_date`. A **zero amount skips conversion entirely**: zero is zero in every currency, and
demanding an FX rate would drop the in-kind transfer rows, which are exactly the ones with no cash. An
unconvertible non-zero currency skips that row with a warning rather than failing the sync.
`test_base_currency_projection_scales_both_metrics` pins the CHF path, since the tests otherwise run on EUR
while production runs on CHF.

### Shared mechanics

The divisor is **clamped to elapsed history** (`partial: true` when clamped), so a
four-month-old portfolio can't report a 12-month average divided by 12; all-time divides by exact days,
not whole months, so a part-month isn't rounded away. `as_of` is injectable purely so tests can pin the
windows. Cash-flow ingestion is a pure additive upsert with no delete, so it needs **no** empty-statement
wipe guard, and an unconvertible currency skips one row rather than failing the sync.

The cheap correctness check: `Σ monthly[].net_eur` must equal the current total cost basis, since every
lot is either still open or was released. **Exact in EUR; approximate once projected.** Each leg is
converted at its own date, so a lot bought and sold months apart contributes `+convert(cost, open_date)`
and `−convert(cost, close_date)` — which cancel to zero only if the rate didn't move. Under CHF the
residual is a fraction of a percent of *closed* cost basis and grows with FX drift, not with error. So
run the identity against `taxlots.cost_basis_eur` (`Σ` of open lots) when you want it to the cent, and
read a small non-zero gap in the base currency as FX, not as a dropped lot. Tests:
`tests/test_contributions.py`, `tests/test_cash_flow_ingest.py`.

---

## Sync schedule (Europe/Berlin)

| Time | Job | Touches Yahoo? |
|---|---|---|
| 00:00 | `ibkr_only_sync_job` — IBKR + FX | no |
| 06:00 | `ibkr_only_sync_job` — IBKR + FX | no |
| 08:00 | `full_sync_job` — IBKR + FX + 730d market data + dividends | **yes** |
| 15:00 | `market_data_only_sync_job` (7d) | yes |
| 22:00 | `market_data_only_sync_job` (7d) | yes |

The two IBKR-only jobs exist because a transient `Code=1001` at 08:00 used to cost a full day of
freshness. They deliberately **skip** market data and yfinance dividends — see rule 1. Pinned by
`tests/test_scheduler_jobs.py`. Status: `GET /api/scheduler/status`.

**Every IBKR attempt must sit outside US market hours, and this is measured rather than assumed.**
IBKR builds a Year-to-Date statement from *finalised* daily data, so `SendRequest` succeeds overnight
and fails mid-session — the failure surfaces as `Code=1001` **at the request step**, which is the
fatal-fast kind, not the "keep polling" kind. This account's own `sync_runs`, read on 2026-07-31:

| Berlin | ET | ok/total | |
|---|---|---|---|
| 00:00 | 18:00 | 1/1 | after the US close |
| 06:00 | 00:00 | 2/2 | |
| 08:00 | 02:00 | 4/5 | |
| 09:00 | 03:00 | 1/1 | |
| 13:00 | 07:00 | **0/6** | pre-market |
| 20:00 | 14:00 | **1/8** | mid-session |

Overnight 8/9; afternoon and evening 1/15. The retries used to sit at **13:00 and 20:00**, where they
were not merely weak but **negative**: every failure is a failed *generation*, and failed generations
are exactly what `Code=1025` counts. Two jobs whose purpose was protecting freshness were spending
lockout budget twice a day to recover nothing. They moved to 00:00 and 06:00 on 2026-07-31.

Keep any future IBKR slot inside roughly **22:00–09:00 Berlin**; a midday one looks helpful and is
not. `test_every_ibkr_job_avoids_us_market_hours` fails the suite if one drifts back.

**Read "we suddenly get constant 1001s" as *we added slots that never worked*, not as a regression.**
The 13:00/20:00 jobs were introduced in `67e6a59` on **2026-07-25** — the same day `sync_runs`
persistence landed, so the oldest record we have (20:00:11 Berlin, a failure) *is* the first retry
ever attempted. Before that only the 08:00 `full_sync` ran, and its success rate has not moved (4/5
that week). Two changes arriving together — new failing slots and, for the first time, a record of
every attempt — read as IBKR getting worse. It had not.

That accounts for the *volume* of failures. It does **not** account for why `1001` started at all,
and the answer to that is the query itself:

| | Flex Query contents |
|---|---|
| before 2026-07-24 | **Open Positions only** |
| `6cccdab` 07-24 | + Trades, CorporateActions, CashTransactions |
| `86960aa` 07-28 | + Deposits & Withdrawals, Transfers |

**One section became six in four days, and five of them scan the whole YTD period.** Open Positions
does not — it is an as-of snapshot, which is why it never provoked this. The 08:00 `1001`s that
motivated adding the retries in the first place began the day *after* the first expansion. So the
chain is: sections added → `1001` appears → retries added at hours that can never work → `1001`
everywhere.

**Do not reason about statement cost from row counts.** Open Positions is ~70% of the *rows* (979
lots) and ~0% of the *scan work*. An earlier revision of this file used the row share to argue that
shortening the period would barely help; that was measuring the wrong quantity.

One hypothesis this does kill: **"failures accumulate into a throttle."** The autocorrelation is
*inverted* — the next attempt succeeds 5/15 after a failure and 0/5 after a success. That is
schedule position, not contagion: 08:00 follows a failed 20:00, and 13:00 follows a successful
08:00. A success 4½ hours after a failure (2026-07-26 00:30) rules out a cooling-off period.

**The period is `Last 30 Calendar Days` as of 2026-07-31, and that is what fixed it.** The evidence
is a clean A/B: a 20:00 failure and a 21:08 success 68 minutes apart, same token, same hour band —
15:08 New York, mid-session, where the day had gone 0-for-8. Statement shape dropped from ~290 trade
rows to 103 and ~107 cash transactions to 17.

It is safe because `reconcile_taxlots` reads trades from the *database*, ingestion is idempotent and
additive, `widen_cash_flows_covered_from` only moves the boundary earlier (a 30-day `from_date` is
ignored, so January coverage stands), and Open Positions is period-independent. Verified after the
switch: all 71 YTD trades still on record, `coverage_from` still 2026-01-09, 979 lots, 0 skipped.

**Do not restore the YTD period to "be safe".** That reintroduces the failure. What it bought — a
statement that re-delivers the whole year every time — is available on demand instead: a browser
download ingested through `app/cli/ingest_flex_xml.py` is idempotent, so it simply fills whatever a
bounded window missed. `find_stale_ibkr_sync` exists to tell you when to do that.

**One pipeline at a time (`app/single_flight.py`).** `/api/` is public — and was unauthenticated when
this was written; `app/auth.py` (below) can now gate the writes, but throttling and authorization are
different jobs and this one is still needed. Nothing stopped concurrent or rapid-fire triggers: APScheduler's `max_instances=1` only fences jobs *it*
dispatches, and `POST /api/scheduler/trigger` ran `full_sync_job()` as a bare coroutine outside the job
store entirely — so a stranger could overlap the 08:00 run or spam Flex requests toward a `1025`
lockout. Everything that can reach IBKR or Yahoo shares the `sync-pipeline` gate; two pipelines racing
is the failure mode regardless of which endpoint started them. Scheduled jobs enter with **no cooldown**
and, on collision, record a `status="skipped"` run rather than running concurrently (the next slot
recovers freshness). The public routes add cooldowns (ibkr 120s; market-data / trigger / fundamentals /
ratings / allocation / watchlist 300s) and answer **429 with `Retry-After`**. In-process by design —
single uvicorn worker, and the check-and-set has no `await` between test and set. A backgrounded route
(fundamentals `/sync`) checks `is_running()` in the handler and holds the lock inside the task, so the
gate spans the actual work rather than the enqueue. **`POST /api/watchlist` (add) is gated too** (60s
cooldown — a single-ticker fetch, lighter than the 300s bulk sync): it fires a per-add `force=True`
yfinance fetch and was the one Yahoo-triggering route the rollout missed, so rapid-fire adds of
distinct tickers were an unthrottled fetch storm. The add itself stays *outside* the gate — busy or
cooling, the row is created with `last_synced` null and the next sync fills it in, rather than a
running 08:00 job turning a bookkeeping action into a 429. Tests: `tests/test_single_flight.py`.

**`GET /api/portfolio/benchmark` is gated at the *fetch*, not the handler** (added 2026-07-30 — it was
the last route with no gate at all; `portfolio.py` never imported `single_flight`). It lazy-fetches
Yahoo and tiles Frankfurter on a cache miss, so looping the 8 keys in `BENCHMARKS` over the 5-year span
the route allows could run beside the 08:00 `full_sync`. It must **not** wrap the handler:
`sync_benchmark_prices()` only refreshes benchmarks that *already have rows*, so this route bootstraps
the warm set — a cache-only GET leaves a first-time selection empty forever, and gating the read would
429 the chart every morning. So the gate sits inside `_ensure_prices_available` /
`_ensure_fx_rates_available` around the network call, and `SyncBusy` serves what is cached.

Two consequences worth keeping straight. **Entering the gate bumps the shared last-start clock every
other route's cooldown reads**, which is why the gate wraps only the actual fetch — a warm chart load
must not 429 a manual IBKR sync. And **the gate cannot stop a sequential loop**, so each ticker and
currency carries its own `UPSTREAM_RETRY_COOLDOWN_SECONDS` (300) attempt memo: trailing weekdays the
provider has no bar for stay missing *by design*, so the range end is otherwise re-requested on every
request forever — the same shape the holiday rule fixed for `market_prices`. Keyed **per upstream
target**, because warming eight distinct benchmarks is legitimate and re-hitting one is not.
`reset_upstream_throttle()` exists for tests, since the memo is process-lifetime state.

`_ensure_fx_rates_available` also asks what is missing before tiling. `_batch_fetch_rates` issues its
request **unconditionally** (it dedups per row, *after* the response), so a five-year chart load cost
~60 provider requests every time regardless of the cache. It now uses the same holiday-aware
missing-days rule as the price path, extracted to `_missing_business_days()` so the two can't drift.

`POST /api/fundamentals/sync` finally carries the 300s this file already claimed for it. `is_running()`
fences only *overlapping* runs, so a poller that waited for each pass to end ran them back to back
indefinitely at ~5 Yahoo calls per security per pass. `cooldown_remaining()` lets a BackgroundTasks
handler answer 429 honestly instead of replying `"started"` to a run the background half then drops.

**Errors are redacted before they are stored or served (`app/redact.py`).** Flex sends the token as a
`t=` URL parameter and `requests` transport errors stringify with the full URL, so a plain `str(e)` from
a failed SendRequest carries it — and those went verbatim into `sync_runs.message`, which the public
`/api/scheduler/status` and `/history` re-serve forever. Production really did leak it (found and
scrubbed 2026-07-28; **rotate the token if this ever recurs**). `SyncRunRepository.record()` redacts on
write and `to_dict()` again on read, so rows written before the fix or restored from a backup can't leak
either; the routers redact their `HTTPException` details. The `q=` query id stays readable — public in
these docs and useless alone. Tests: `tests/test_secret_redaction.py`.

**A price that never arrives is otherwise silent.** `portfolio_service` values a position with no price
at **0.00** and moves on, so deleting SBI's poisoned prices took 446.93 CHF off the total with nothing
reporting it. `find_stale_priced_securities()` now runs after every market-data sync and warns when a
security **with open lots** has no cached price at all, or none newer than `STALE_PRICE_DAYS` (5 —
enough to absorb a weekend plus a holiday). Closed-out holdings are excluded: they legitimately stop
getting prices, and warning on them would be permanent noise.

**A sync that never *succeeds* is silent in the same way.** Individually a failed IBKR run is
unremarkable — `1001` is routine and the schedule shrugs it off — so the thing worth alarming on is
the **absence of a success**, not any single failure. `find_stale_ibkr_sync()` warns after
`IBKR_SYNC_STALE_DAYS` (7) with no successful run of an `IBKR_SYNC_TYPES` sync. Three details carry
the weight:

- It runs from the **market-data** job, not an IBKR one. Market data succeeds while Flex is refusing,
  so the warning still reaches `warnings[]`; hanging it off the IBKR job would silence it in exactly
  the outage it exists to report.
- **`ibkr_manual_xml` counts as a success.** Ingesting a browser download genuinely refreshes the
  data, so the documented escape hatch from a token lockout must reset the clock — otherwise the
  alarm blares through the correct recovery and trains the reader to ignore it.
- An **empty** history is quiet (fresh install), but *attempts with no success ever* warns. Those are
  different states and collapsing them would either cry wolf on day one or hide a broken token.

This is what makes **shortening the Flex Query period** safe. Under Year-to-Date a gap costs only
freshness, because every statement re-delivers the year; under a bounded window trades that fall out
of it before a sync succeeds are gone from every future statement. Seven days against three IBKR
attempts a day is ~21 consecutive failures, so it cannot fire over a `1025` lockout (~14h).

`_collect_warnings()` hoists each step's warnings to the top of the job's result, because `_record_run`
reads `result["warnings"]` and a job's own dict never had that key — so warnings were being buried in
`details` and never rendered as warnings.

**The job store is persistent, and two details make it actually work.** APScheduler runs in-process, so
a `docker compose down` overlapping a Berlin slot used to drop that slot outright — which is what
happened to the 2026-07-30 08:00 `full_sync`. A `SQLAlchemyJobStore` (`settings.scheduler_jobstore_url`,
a **separate** sqlite file: the store is synchronous SQLAlchemy while the app is aiosqlite/WAL) plus
`coalesce=True` and `MISFIRE_GRACE_SECONDS` (1800) runs the missed job on startup instead.

- **The registered targets are module-level functions** (`full_sync_job_entry` and friends), not the
  bound methods they were. A persistent store serializes each job, and pickling `self.full_sync_job`
  drags the live `AsyncIOScheduler` in with it.
- **`_add_or_keep()` exists because `add_job(replace_existing=True)` recomputes `next_run_time` from
  now** — it would overwrite the missed timestamp on the way in and make the persistence pointless. An
  identically-triggered job is left alone; comparing `str(trigger)` is what lets a genuine schedule
  change still replace one. Both directions are pinned in `tests/test_scheduler_jobs.py`.

Thirty minutes is chosen from both ends: long enough for a `build --no-cache` rebuild, short enough
that a real outage doesn't dump four stale slots onto a cold container.

**`/api/` protections that are not `single_flight`.** Three middlewares in `app/main.py`, innermost
last, so a rejection from any of them still carries a correlation id:

- **`app/auth.py`** gates every `POST/PUT/PATCH/DELETE` under `/api/` on `settings.api_admin_token`
  (`X-API-Key`, or `Authorization: Bearer`, compared with `secrets.compare_digest`). It is
  **middleware, not a per-route dependency**, deliberately: every router takes only `Depends(get_db)`,
  so a dependency would have to be added to ~14 routes and remembered on every route added later —
  keying on the HTTP method means a new `POST` is covered the moment it exists, and
  `test_every_mutating_route_is_covered_without_being_annotated` walks the live route table to prove
  it. **Empty token = disabled**, so shipping it could not 401 the running site; startup warns loudly
  while it is off, the same treatment `SCHEDULER_ENABLED` gets. Reads stay open because the frontend
  has no login and gating them would black out the UI.
- **`app/rate_limit.py`** is a fixed-window per-client counter (`RATE_LIMIT_PER_MINUTE`, 0 disables).
  `single_flight` fences the sync *pipelines*; nothing bounded the expensive anonymous reads. Keyed on
  the first `X-Forwarded-For` entry, since nginx makes `request.client.host` always loopback — forging
  it only splits the forger's own bucket. `/health` is exempt: the deploy script polls it.
- **`app/observability.py`** stamps `X-Request-ID` (reusing a plausible inbound one so it correlates
  across a proxy) and installs the handler for unhandled exceptions — the one path where `str(e)`
  still reached the client unredacted. The body is a fixed string plus the id; the log line goes
  through `redact_secrets`.

`tests/conftest.py` neutralises the limiter's process-lifetime window state and the job-store path for
the whole suite, or one module's traffic would 429 another's. Tests: `tests/test_api_hardening.py`.

---

## Activity ledger

`GET /api/portfolio/activity` (+ `.csv`) → `ActivityService`, rendered by `ActivityTab.tsx`. It unions
**trades, corporate actions, cash flows and dividends** into one chronological list with date-range,
kind and symbol filters.

It exists because all four tables were ingested, reconciled and depended on — the tax report reads
`trades`, the contributions splice reads `cash_flows`, `reconcile_taxlots` reads `corporate_actions` —
with **no read surface at all**. The sharpest consequence: the transfer audit this file prescribes
before trusting any money-added figure was `manage_cash_flows list` over ssh. Every cash row now
carries `counts_as_money_in`, badged *Transfer · not money in*.

Four rules, each of which would be a bug the other way:

- **Paging is applied to the merged list, not per table.** The four sources are separately ordered, so
  a per-table limit would silently drop every dividend in a busy trading month.
- **Dividends are dated by `pay_date` falling back to `ex_date`** — the same `coalesce`
  `has_ibkr_dividends` uses. yfinance stores under the ex-date and IBKR under the pay date, and
  Mastercard's 29-day lag exceeds a monthly cycle, so the column asked decides the window.
- **Amounts convert at each row's own date** through the same `BaseFx` every other read endpoint uses.
- **A field a kind cannot fill is `None`, never 0** — in JSON and in the CSV. A corporate action has no
  price, and a `0.00` would assert one.

Zero-value dividend rows are excluded on the same test the two dividend readers use, so yfinance's
pre-ownership history never surfaces. Tests: `tests/test_activity_service.py`, plus cases in
`tests/test_api_smoke.py`.

---

## Client-side analytics — risk, targets, currency

Three pure `frontend/src/lib/` modules with no endpoint of their own: they compute from series and
positions the page has already fetched, which is why they add **no request and cannot reach Yahoo**.
`portfolioKpis.ts` feeds the Performance tab's two card rows; `rebalance.ts` and
`currencyExposure.ts` feed two panels on the Allocation tab.

**One rule spans all three, and it was a real bug before it was a rule.** `undefined` data means
*not loaded*; an empty array means *nothing held*. Collapsing them lets a panel build a confident
answer out of an outage — the rebalance panel did exactly that, reporting *0 positions outside the
band* above rows reading *Not currently held*, i.e. that nothing needed rebalancing and that held
positions were not held. Unit tests could not see it because the shape needs a saved target;
`e2e/errors.mjs` covers it now. Any new panel here takes `isError` and treats absent data as a
stated failure.

### Risk metrics (`portfolioKpis.ts`)

Sharpe, Calmar and top-5 weight predate the rest. Volatility, Sortino, beta/correlation, drawdown
detail and Herfindahl effective holdings were added because the tab reported return *per unit of
risk* without ever reporting the risk, and because a top-5 weight cannot tell five equal positions
from one dominant one.

- **Beta is measured only over days when NEITHER series saw a flow.** The benchmark is a flow-matched
  hypothetical carrying the portfolio's own cost-basis line but no `external_flow_eur`, so netting a
  flow out of it means inferring one from the cost delta — the same asymmetry that fabricates a loss
  on every sale date in `externalFlow`'s fallback. That would bias beta on exactly the days the
  portfolio traded. Dropping the pair costs a few days a month and biases nothing. `sampleDays` rides
  along so a thin window declares itself instead of showing a confident slope.
- **Volatility and Sortino are `null`, not `0`**, below the minimum sample or with no downside at all.
  A `0` meaning "unknown" being read later as a fact is the most repeated bug in this codebase.
- **`dailyReturnSeries` exists because `dailyReturns` drops days with nothing to divide by**, so the
  nth return is not the nth calendar point. Indexing the input by return position to name a
  drawdown's peak picks the wrong day.
- **The *current* drawdown leads and the worst one is the footnote.** Showing only the max reads as a
  live warning long after the recovery.

### Target allocation and drift (`rebalance.ts`)

Targets live in **localStorage**, following `ForecastTab`'s precedent. Deliberately not a table plus
an endpoint: `/api/` is proxied publicly and every write is auth-gated, so a route that stores
portfolio intent is a larger surface than this earns. The cost — targets do not follow you to another
browser — is stated in the panel. `readTargets()` drops a stored value that is not a usable percent
rather than coercing it, because one NaN propagates into every drift on the page, and survives
corrupt JSON rather than taking the tab down.

Four rules, each a wrong number the other way:

- **A missing target means unmanaged, never 0%.** Reading absence as zero advises liquidating every
  holding whose target has not been set — all of them on first use. Clearing the input therefore
  *removes* the target; `0` means "hold none of this", and those are different instructions.
- **Targets are never renormalised to 100%.** The shortfall is reported instead. Scaling invents a
  target nobody chose, and the invented one moves whenever an *unrelated* target is edited.
- **An unpriced position has no weight rather than a zero weight.** The portfolio values a holding
  with no cached price at 0.00, so naive drift advises buying its entire target when the position may
  be the largest one held — the SBI shape. A *priced* holding genuinely worth zero is a real 0% and
  stays advisable.
- **Targets key on `security_id`, not symbol**, because identity is `isin + exchange` and ASML is two
  securities.

Two further refusals. An empty plan is **not** `balanced` — vacuous truth renders *nothing to do* on
a portfolio nobody has configured. And `judgedCount` exists because counting only rows *outside* the
band cannot tell an all-clear from an empty comparison: zero judged rows must say so, which is also
wrong-with-a-healthy-backend when every target sits on an unpriced holding.

### Currency exposure (`currencyExposure.ts`)

`securities.currency` is the currency a listing **trades** in. For a direct holding that is also the
economic exposure; for a fund it need not be, and here often is not — a EUR-listed S&P 500 tracker is
quoted in EUR and carries USD risk. Folding it into the EUR bucket is confidently backwards on
exactly the positions that prompt the question.

**Nothing is re-attributed, and the ETF look-through table cannot fix it**: `app/etf_mappings.py` maps
*regions*, and regions do not determine currency — "Europe" spans EUR/GBP/CHF/SEK, "Asia Pacific"
spans JPY/AUD/HKD/TWD. Funds are counted where they trade, with their share of the book named on
screen and the reason given, so the rows cannot be mistaken for an FX position. The fund set comes
from the ETF bucket of the allocation response already on the page, since `Position` carries no asset
type; matching is by symbol, so a stock sharing a held fund's ticker would be flagged — accepted,
because the flag is a caveat rather than a figure.

Unpriced positions are excluded and counted, as above, and `foreignQuotedPct` returns `null` rather
than `0` when nothing is priced: no positions is an unknown exposure, not an unhedged-free one.

Tests: `src/lib/portfolioKpis.test.ts`, `src/lib/rebalance.test.ts`,
`src/lib/currencyExposure.test.ts`, plus jsdom tests beside each component and three checks in
`e2e/errors.mjs`.

---

## Deployment

**Push to `main` → deployed automatically within 10 minutes.** `/root/auto-deploy.sh` on the VPS (root
crontab, `*/10 * * * *`) does: `flock` → `git fetch` → deploy **only if strictly behind** `origin/main`
(`merge-base --is-ancestor`; it will refuse and log if the VPS has diverged) → back up `portfolio.db` →
`deploy.sh` → health check → **roll back to the previous commit if health fails**. Log:
`/root/auto-deploy.log`.

`deploy.sh` is expensive (`docker compose down`, `build --no-cache`, `npm ci`), which is why the cron
guards on an actual change. Its own health check fires a few seconds after start and often reports
FAILED spuriously — check `/health` again after ~15s before believing it.

- SSH: `ssh -i ~/.ssh/id_ed25519_hostinger root@portfolio.srv1211053.hstgr.cloud`
- Secrets live only in `/root/IBKR_investment_tracker/backend/.env` (`IBKR_TOKEN`, `IBKR_QUERY_ID`)
- nginx proxies all `/api/` publicly with `proxy_read_timeout 300`; needs `listen [::]:443/80` (an AAAA
  record exists)
- Backups: `/root/ibkr-backups/<date>/`

**Changing `backend/.env` needs `docker compose up -d`, never `restart`.** Compose reads `env_file`
when it *creates* a container; `restart` reuses the existing one with its original environment, so a
new value is accepted, written, and silently ignored. `up -d` sees the changed config and recreates.
This bit us turning on `API_ADMIN_TOKEN` (2026-07-31): the token was in `.env`, every command
reported success, and `write_auth_enabled` stayed `false` — a site that looks locked down and isn't.
**Always confirm against `/health` rather than the command's exit status.**

**`deploy.sh` pulls the repo itself (line 13), so a deploy that changes `deploy.sh` runs the OLD
copy once.** Bash does not reload a running script. Any behaviour newly added to `deploy.sh` is
therefore absent from exactly the deploy that introduces it, and appears from the next one on. That
is why the build-identity deploy reported `commit: "unknown"` — the `GIT_COMMIT` export existed in
the pulled file but not in the executing one. Expect this for any future `deploy.sh` change; it is
not a failure, and it self-corrects. Anything asserting "the deploy landed" must therefore not key
solely on the commit sha (`ops/finish-deploy.*` also accept the `write_auth_enabled` marker).

A **cloud routine** `ibkr-sync-validator` (claude.ai/code/routines) runs daily at 07:45 UTC to validate
the morning sync via the public API + the IBKR MCP connector. It **cannot SSH**, so it opens PRs rather
than pushing to `main`.

---

## Local development

```bash
cd backend && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev          # http://localhost:5173
```

**Set `SCHEDULER_ENABLED=false` in `backend/.env` for any local run.** Starting the backend is not a
neutral act: the lifespan handler arms the 00:00/06:00/08:00/15:00/22:00 Europe/Berlin jobs, which call
the live Flex API with the real token from `.env` and hit Yahoo — both rules at the top of this file,
from a dev machine. `settings.scheduler_enabled` defaults to **True** so production is unaffected, and
a disabled scheduler logs a warning because otherwise it looks exactly like a healthy site whose data
has quietly stopped moving. Pinned by `test_scheduler_is_enabled_by_default`.

Two traps when pointing a browser at a local stack:

- **Check which port Vite actually took.** If 5173 is occupied it silently moves to 5174 and prints it
  once. A second dev server on 5173 configured against production means you are looking at prod data
  and issuing requests to the live site — including `/api/dividends/summary`, which can enqueue a
  Yahoo dividend sync.
- **A real-data snapshot beats the stale local DB.** `sqlite3 .backup` on the VPS, copied down, and
  `DATABASE_URL` pointed at it (the local `backend/portfolio.db` predates trades, cash flows and
  the IBKR dividend era, so it exercises none of the interesting shapes). Delete the copy afterwards —
  `*.db` is gitignored, but it is real account data.

`tests/test_api_smoke.py` runs **every read endpoint through the real HTTP stack** against a fixture
carrying the shapes that actually break: a dual-listed ticker, a closed lot, a dividend row with a NULL
net, a pre-ownership zero row, a non-EUR security, CHF as base. Every other test calls services
directly, which is how a `Decimal + None` reached production behind a green suite. `yfinance` is a
raiser for that whole module, so an accidental network reach fails loudly; `/api/portfolio/benchmark`
is excluded because it lazy-fetches Yahoo on a cache miss, and POST routes are excluded because they
start real syncs. **Add a case here when an endpoint's response shape changes.**

Tests (462 backend + 91 frontend, all offline — no IBKR, Yahoo or FX-provider calls):
```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q
cd frontend && npx tsc -b && npm run test && npm run build
```

Useful:
```bash
# masked token check (never echo the whole thing)
grep -o '^IBKR_TOKEN=.\{0,4\}' backend/.env

# data snapshot on the VPS
python3 -c "
import sqlite3; c=sqlite3.connect('/root/IBKR_investment_tracker/backend/portfolio.db')
c.execute('PRAGMA busy_timeout=30000')
for q in ['select count(*) from securities','select count(*) from taxlots where is_open=1',
          'select count(*) from trades','select source,count(*) from dividend_payments group by 1']:
    print(q, c.execute(q).fetchall())"
```

---

## Ticker mapping & currency

**Ticker mapping** (`market_data_service.py`) — three tiers: custom `ticker_mappings` row → exchange
suffix → try variations (`.DE`, `.F`, `.L`, bare), then auto-save what worked.
`EXCHANGE_SUFFIXES`: `XETRA`/`IBIS2`→`.DE`, `LSEETF`→`.L`, `AEB`→`.AS`, `KRX`→`.KS`, `TWSE`→`.TW`;
`TSE` is Tokyo (`.T`) **except** for CAD listings, where IBKR means Toronto (`.TO`). Add new exchanges
here when a security has no prices, and verify a ticker in a browser first.

**A wrong auto-discovered mapping is sticky and silent** — the failure that put `SBI@TSE` (Toronto, CAD)
on a US fund for months. The last variation tried is the **bare symbol**, which readily matches an
unrelated US listing of the same ticker; it fetched cleanly, so it was auto-saved — and because tier 1
(`ticker_mappings`) is consulted *first*, that row then shadowed the `.TO` suffix logic even after the
logic was fixed. `_get_currency_from_ticker()` compounded it: with no suffix to read it fell back to
"use the security's currency", stamping USD prices **CAD**, so nothing downstream could see the
mismatch. Result: the position was carried 61% high (7.70 vs 4.78 CAD).

Two guards now: prices carry **the currency Yahoo reports** (read from the history metadata already in
the response — no extra request), and a variation whose currency disagrees with the security's is
**rejected, not adopted, and not saved**. Tests: `tests/test_market_data_service.py`.

### Managing mappings — `app/cli/manage_mappings.py`

This table decides where every price comes from and was the last one still edited by hand-written SQL
over ssh, where a typo mis-prices a position and looks like a real price. Use the CLI instead:

```bash
docker exec backend-portfolio-backend-1 python -m app.cli.manage_mappings list
docker exec backend-portfolio-backend-1 python -m app.cli.manage_mappings set 2330 TWSE 2330.TW
docker exec backend-portfolio-backend-1 python -m app.cli.manage_mappings disable SBI TSE --purge-prices
```

- **`list`** prints the security's currency beside the one its Yahoo ticker implies. A disagreement
  between those columns *is* the SBI bug, so it's flagged explicitly rather than left to be noticed in
  the portfolio total.
- **`set`** stamps `source='manual'` and **refuses** a ticker whose suffix contradicts the security
  (`SBI.L` → GBP under a CAD security). It reuses `_get_currency_from_ticker()`, so the CLI and the
  fetch path can't drift apart. A *bare* ticker implies no currency and so can't be refused — for a
  foreign listing it warns loudly instead, since that's the exact SBI shape. Storing a mapping before
  the security exists is allowed on purpose: that's how you pin one ahead of the statement.
- **`disable`** sets `is_active=False` rather than deleting (`get_mapping()` already filters on it), so
  the row stops being consulted while the record of what was tried survives. **`--purge-prices`** is the
  whole recovery in one step: drop the prices **and the yfinance dividend estimates** the bad mapping
  produced, and let a scheduled job refill them — incremental caching fetches only missing dates, so
  it costs **no ad-hoc Yahoo call**. IBKR dividend rows are never touched. It purged prices only
  until 2026-07-30, which is how SBI's poisoned estimates outlived its mapping fix.
- `--dry-run` on both mutating commands; every edit records a `sync_runs` row (`manual_mapping`),
  because a mapping change being invisible is why SBI went unnoticed for months.

Tests: `tests/test_mapping_cli.py`.

**Currency** — Frankfurter at `https://api.frankfurter.dev/v1` (`.app` now 301-redirects here).
Batch-fetches date ranges (one call per ~30 days) and carries the last known rate forward across
weekends/holidays.

Frankfurter republishes the **ECB reference rates**, so its list is fixed at the ECB's 30 + EUR and will
never include TWD, RUB, QAR or SAR. That is not cosmetic: an unconvertible currency makes
`reconcile_taxlots()` skip the lot, so the holding vanishes from the portfolio *and* the tax report
(counted in `taxlots_skipped`, reported in `warnings[]`). Buying TSMC on TWSE hit exactly this.

So `CurrencyService` falls back to `https://open.er-api.com/v6/latest/EUR`, tagging rows
`source='er-api-latest'`. It is EUR-based (`rate = rates[to] / rates[from]`) and **latest-only — there
is no free historical endpoint**, so it is used only within `FALLBACK_MAX_AGE_DAYS` (7) of today and
refuses older dates rather than backdating a current rate onto an old tax lot. Never raises;
`get_exchange_rate()` owns that decision.

`get_exchange_rate()` resolves in this order, and the order is the design:
**cache → Frankfurter → carry-forward → fallback → carry-forward → raise.**

- Carry-forward comes *before* the fallback because Friday's real ECB rate beats today's
  approximation over a weekend. It preserves the source tag of the row it copies.
- The fallback now also covers currencies that *are* in `SUPPORTED_CURRENCIES` when Frankfurter
  answers with nothing. That demotes the hardcoded list from load-bearing to advisory: a provider
  outage or the ECB list drifting degrades the rate instead of erasing a position (a raise here makes
  `reconcile_taxlots()` skip the lot, so the holding disappears from the portfolio *and* the tax
  report). It is never reached while Frankfurter is answering — no silent provider switching.

**`WARM_CURRENCIES`** (`TWD, CNH, AED, SAR, QAR, KWD, RUB, CLP, COP`) is warmed daily by
`sync_exchange_rates` alongside the currencies actually held, via `warm_rates()`. Only currencies
Frankfurter *cannot* serve are listed, because those are the ones whose history can only accumulate
forward — an ECB rate is retrievable at any time, so warming it would be waste. The whole set costs
**one** request (`_fetch_fallback_table()` returns all ~166 at once), which is what makes daily
affordable. Without it, TWD only got a rate on days a lot happened to need one, so missing the 7-day
window once meant the lot was skipped forever. Extending the list is one edit and no extra request.

Tests: `tests/test_currency_fallback.py`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `has no attribute` / `is not a valid` in a sync | IBKR schema drift. `_sanitize_flex_xml` should absorb it — if not, extend it generically (never patch one field) + add a test |
| `Code=1025` | Token lockout, usually self-inflicted. **Wait**, don't retry. The schedule recovers it |
| `Code=1001` | Not ready. Polled while retrieving; **fatal at the request step** — never re-request, a later job handles it |
| Sync 200 but 0 trades | Flex Query section/period not covering them |
| `dividend_source` stuck on `yfinance_estimate` | No `<CashTransactions>` ingested — check the section + Withholding Tax option |
| Yahoo 404/429 | **Stop.** Wait 30-60 min. Check `yfinance >= 1.1.0` |
| A position is missing from the portfolio | Check `taxlots_skipped` + `warnings[]` on the sync run — usually a currency neither FX provider covers |
| A position shows 0.00 / `market_price: null` | No cached price. The market-data sync's `warnings[]` now names it. Fix the `ticker_mappings` row, or fill it with `app/cli/import_prices.py` from IBKR bars |
| The chart steps at a split date | Cached pre-split closes. A *new* split purges them automatically; for an older one delete that security's `market_prices` and let 08:00 refill |
| A new currency appears | Nothing to do if it's in `WARM_CURRENCIES` or the ECB set. Otherwise add it there — one edit, no extra request |
| "Money added" spikes in one month | A transfer booked as a deposit. `manage_cash_flows list`, then `reclassify <ib_key> --as TRANSFER_IN`. **Never** trust an Added figure without eyeballing that list first |
| "Money added" is blank or `—` | Expected before `deposits_from`: no IBKR deposit ledger exists for the pre-transfer years. Not a bug — Deployed covers that era |
| Realized gains look low + a `warnings[]` entry names a currency | No FX rate for that trade date, so the sale was **omitted** rather than mis-scaled. Check `WARM_CURRENCIES` covers it |
| Steuerwert reads `—` instead of a number | `holdings_snapshot_error`: the snapshot raised. Check the logs — this is deliberately *not* 0.00 |
| A dividend forecast looks invented | Check `forecast_samples` on the breakdown row — n≤2 is a guess. Then `manage_mappings list` for `DIVIDENDS PREDATE MAPPING`, and purge with `purge_dividend_estimates` |
| A trailing yield looks far too low | `trailing_yield_partial`: the position wasn't held a full year, so partial income is over a full position value. Not a bug, and deliberately not annualized |
| A position's value is far off IBKR's | Suspect the `ticker_mappings` row before the price feed: run `manage_mappings list` and look for a currency disagreement, then compare `market_prices.close_price` against IBKR's `market_price` in the *same* currency |
| App total ≠ IBKR total | Compare against `gross_position_value`, **not** net liquidation (which adds cash); and intraday the app holds the last *close* while IBKR quotes live |
| Site "down" in the browser | Often TIM home DNS, not the server — verify with `Test-NetConnection`, not `nslookup` |
| Deploy says health FAILED | Usually the premature check; re-curl `/health` after ~15s |
| A write returns 401 | `API_ADMIN_TOKEN` is set and the browser has no key. Lock button in the header; the same value goes in `backend/.env` |
| A request returns 429 with `Retry-After` | Either the sync cooldown (`single_flight`) or the per-IP limit (`RATE_LIMIT_PER_MINUTE`). The response body says which |
| "Which build is live?" | `curl /health` — it reports `version`, `commit`, `scheduler_enabled` and `write_auth_enabled`. Same line in the app footer |
| A 500 with no detail | By design. Grep the container log for its `request_id`, which is in the body and the `X-Request-ID` header |
| A missed sync ran late after a restart | Expected: the persistent job store honours a misfire for 30 min. Older than that is dropped, and the next slot recovers |
| A drift row reads `—` instead of advice | No target (unmanaged — blank is not 0%), or the position has no cached price so it has no weight to compare. Both deliberate; see *Client-side analytics* |
| Drift says "no target could be compared" | Nothing had both a target and a weight. **Not** an all-clear — that wording exists because "0 outside the band" was one |
| A drift or currency panel says it couldn't load positions | The positions query failed. The panel refuses to build a plan from absent data rather than reporting a portfolio of unheld rows |
| Currency exposure looks wrong for an ETF | It is quote currency, not economic exposure, and deliberately not re-attributed — a EUR-listed S&P tracker is EUR-quoted with USD risk. The fund share is named on screen |
| Beta is blank with a benchmark selected | Fewer than the 20 flow-free days a regression needs; the count so far is in the footnote. Flow days are excluded by design |

---

## Correctness sweep (2026-07-29)

A three-part audit (valuation core / API surface / frontend) produced 16 fixes, all shipped and
deployed overnight; the test suite went 190 → 241. The ones that changed **stated behaviour** are
documented in place above — token redaction and the single-flight gate under *Sync schedule*, the
close-date convention, disposal inflows and the swept timeline under *Reconciliation*, the era splice
and forecasts under *Dividends*, the holiday rule under *split invalidation*. Also fixed and worth
knowing: the FX carry-forward is now bounded at **30 days** (it had no bound, so a months-stale rate
could be stamped onto a new lot's persisted `cost_basis_eur` — past the bound it raises and the lot is
skipped *with* a warning, which self-heals); the price-currency map picks the **newest** row
deterministically and warns on a mixed history instead of applying an arbitrary row to the whole series;
two composite indices were added (`taxlots(security_id, is_open)`,
`exchange_rates(from_currency, to_currency, date)`); and the UI now renders sync **warnings** (they ride
on *successful* runs and were structurally unreachable before — the SBI silent-failure class) and shows
an explicit error state instead of "No portfolio data — sync to get started" when the backend 500s.

## Current state (2026-07-28)

**40 securities, 36 open positions, 975 open tax lots, 67 trades, 62,178.99 CHF.** The 27 Jul
statement was ingested **offline** from a browser download (`ibkr_manual_xml`, 04:16 UTC) rather than
waiting on the Flex API, because three consecutive IBKR jobs had returned a plain `1001`. That is the
escape hatch working as designed: no token spend, no `1025` exposure, and `full_sync` re-ingesting the
same statement afterwards is idempotent.

`taxlots_skipped: 0`, `prices_invalidated: 0`, no "unsupported currencies" warning, and
`find_stale_priced_securities()` returns empty — every held security has a current price.

**The external cash ledger is live on production.** The Flex Query now carries
Deposits & Withdrawals (at **Detail**) and the **Transfers** section (at **Transfer** level, not Lot —
Lot would emit a row per transferred lot and bury the cash leg in the list that has to be audited).
The statement ingested **47 cash flows = 25 deposits + 22 in-kind transfers**, 0 skipped, and
**0 reclassified** — correct, because the transfer carried no cash (see the contributions section).
No manual reclassification was needed, so the automatic guard has never had to fire on this account.
`manage_cash_flows list` shows all 22 transfer rows as *not* counted, which is the audit to run before
trusting any money-added figure.

It reached production through the **offline path** (`ibkr_manual_xml`), not the Flex API: three
consecutive IBKR-only jobs had returned a plain `1001`, so a browser download was ingested instead —
no token spend, no `1025` exposure, and the next `full_sync` re-ingests the same statement idempotently.

`deposits_from` lands a few days *before* the transfer date, so the ledger genuinely starts at the
account's first funding. The set includes one real withdrawal (negative amount, sign preserved) and one
CHF deposit against an otherwise-EUR ledger, which is what exercises the FX path end to end. Note IBKR
sends the **legacy** `type="Deposits/Withdrawals"` spelling, not `"Deposits & Withdrawals"` — ibflex maps
both to `CashAction.DEPOSITWITHDRAW`, so nothing special is needed, but don't "fix" the enum comparison
if that string looks wrong.

`coverage_from` = the ledger's **first row**, in the second week of January — *not* the statement period
start, which is 1 Jan because the query is YTD. The account's first deposit and its first execution land
on the same day, so that is genuinely the date IBKR becomes the whole picture; the clamp described in the
contributions section is what stops the pre-account days of January being claimed as covered and their
purchases dropped. The incoming transfer arrives *later* than that date, which is why the boundary is the
ledger start and not the transfer. All-time and 12M come out `spliced`; 6M and 3M run on
**deposits alone** and are already rotation-proof.
Where both sources overlap they agree to within **~12%** — two independent derivations (lot cost basis
vs. the cash ledger) landing that close is the best available evidence that the pre-ledger lot-based
figures were sound. `Σ monthly[].net_eur` matches the open-lot cost basis **to the cent in EUR**; in CHF
it lands a few francs off, which is the per-date FX projection on four closed lots and not an error —
see the identity check in the contributions section.

**That statement carried a large IBKR schema drift and needed no code change.** 20+ new attributes
(`figi`, `issuerCountryCode`, `serialNumber`, `weight`, `subCategory`, `exDate`, `dividendType`,
`origTransactionID`, `initialInvestment`, …) plus a `Trade.notes` value `RI` that ibflex can't convert
to its enum tuple. `_sanitize_flex_xml()` dropped all of them generically. This is the case the
sanitizer was written for — don't start patching attribute names.

**The two new positions both landed cleanly.** `2330@TWSE` (TSMC, 12 sh, TWD) and `SOXQ@NASDAQ`
(7.5 sh, USD), both bought 2026-07-27. They worked because the FX rates their lots are valued at were
already cached for that exact date (`reconcile_taxlots` uses `open_date`) — without the TWD row TSMC
would have been silently skipped. `2330/TWSE → 2330.TW` is pinned `manual`; **SOXQ deliberately has no
mapping** and resolved through the bare ticker, which is correct: `NASDAQ` gives an empty suffix, so
that *is* what tier 2 produces, and with no suffix `_get_yahoo_ticker_variations()` returns a single
candidate — the bare-symbol auto-save that poisoned SBI is never reached.

**SBI is fully repaired: 4.79 CAD / 276.83 CHF, 501 cached prices.** Its poisoned rows were deleted
(backup: `/root/ibkr-backups/sbi-poisoned-2026-07-27.json`), 20 days were imported from Client Portal
bars (`source='ibkr'`, `2026-06-29..07-27`) and Yahoo later filled the other 481 via the `manual`
`SBI/TSE → SBI.TO` mapping. The two windows don't overlap — the imported dates were never re-fetched,
exactly as `get_missing_dates()` implies. Yahoo's 27 Jul close for `SBI.TO` came back at **4.79 CAD**,
identical to IBKR's own bar, which independently confirms both the mapping and the import.

Dividends: 57 cash-transaction rows → 26 IBKR dividend payments, all with real withholding, running
from mid-February. 2026 reports `dividend_source='ibkr'` and `realized_source='trades'`; realized is
a small net loss over 4 closed lots. The tax report's `holdings_snapshot_total` matches the portfolio
summary to the cent, which is the shared-code guarantee holding.

Figures are described rather than published, as elsewhere in this file — the repo is public, and a
pasted total also goes stale silently: the ones that used to sit here were superseded when the manual
XML re-ingest upserted corrected amounts, and read as a discrepancy months later. **Check the numbers
against the API or the DB, never against this file.** The reconciliations worth keeping are the
*relationships*: per-date FX means the IBKR EUR net and the tax report's base-currency net differ by a
percent or two rather than matching exactly, and the breakdown's year total is the IBKR era plus the
estimates that precede its boundary.

**Reconciled against IBKR to 0.12%** on 2026-07-27. Compare the app against `gross_position_value`,
never net liquidation (which adds cash and accrued dividends) — "buying power" is a margin metric
derived from that same cash, not a separate bucket.

Cross-checked against IBKR via the MCP connector: IBKR lists **282 YTD trades = 218 `CASH`** (FX
conversions, correctly filtered out) **+ 64 `STK`**, and the 64 match ours symbol-for-symbol. Same-day,
same-price pairs (e.g. NU 7 @ 17.205 twice on 2026-02-04) are **genuine separate fills**, not duplicates.

**Prior years remain estimates** — the rolling 30-day query can't reach them. Backfilling 2025 needs a one-off period
change in the Flex Query (see the tax section); until then 2025 correctly reports
`dividend_source='yfinance_estimate'`.
