# IBKR Portfolio Analyzer — Project Guide

Full-stack portfolio tracker for an Interactive Brokers account. Tracks securities, tax lots, trades,
corporate actions and dividends; renders cost-basis vs. market-value charts; and produces a Swiss tax
report. All values are stored in EUR and projected into a switchable base currency (currently **CHF**).

**Live:** https://portfolio.srv1211053.hstgr.cloud · **Repo is PUBLIC** (never commit account data)

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

## Tech stack

**Backend** — FastAPI (async), SQLAlchemy 2.0 + aiosqlite (WAL), Alembic, APScheduler,
`ibflex` **0.15** (pinned), `yfinance` >= 1.1.0, Frankfurter API for FX.
**Frontend** — React 18 + TypeScript + Vite, TanStack Query, Recharts, Tailwind + shadcn/ui.

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

**General config that matters:** Format **XML**; Period **Year to Date** (Trades/CashTransactions only
contain rows *inside* the period — "Last Business Day" would mean historical trades never arrive);
Date `yyyyMMdd`, Time `HHmmss`, separator `;`. **Never use `dd/MM/yyyy`** — ibflex assumes US
`MM/dd/yyyy` for ambiguous formats and would silently swap month and day.

Prior tax years need a one-off period change (e.g. 2025), then set back to YTD. Ingestion is idempotent
(upserts keyed on `ib_key`), so re-syncing is safe.

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

There is deliberately **no upload endpoint**: `/api/` is proxied publicly and unauthenticated, and a route
that rewrites tax lots is a far larger surface than a CLI run over ssh.

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
  `market_data_only` | `ibkr_manual_xml` | `manual_prices` | `manual_mapping` | `manual_cash_flow`,
  `status`, `message`,
  `details`, `warnings`). Timestamps are
  serialized UTC-aware via `utc_iso()` — a bare naive `isoformat()` is parsed as *local* by the browser,
  which once made an 08:00 sync display as 06:02.
  `SchedulerService.last_sync_result` is in-memory only and auto-deploy restarts on every push, so
  without this the daily validator can't tell "no sync ran" from "the container restarted".
  `/api/scheduler/status` falls back to it; `/api/scheduler/history?limit=N` lists recent runs.
  Recording is best-effort — it must never fail a sync or mask the real error.

Migrations: `cd backend && alembic upgrade head` (the container CMD runs this on every start).

---

## Reconciliation & realized P&L

`reconcile_taxlots()` (`sync_helper.py`) explains quantity changes in priority order:
1. **SELL trades** → close lots FIFO with the real date/proceeds/`fifoPnlRealized`; `close_source='trade'`
2. **Corporate actions** → deterministic reclassification (split/spinoff/merger), not a sale
3. **Fallback heuristic** (quantity drop + `COST_CONSERVED_RATIO`) → `close_source='heuristic'`

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
so the two can never disagree — they did once, and that was a bug.

**A split also invalidates the cached prices.** Yahoo restates historical `Close` after a split, but
`get_missing_dates()` only fetches dates we *don't* have, so pre-split rows are never refreshed while
IBKR restates the lot quantity immediately — leaving a step change in the chart that nothing detects.
So `invalidate_prices_for_splits()` deletes `market_prices` up to and including the action date
(`MarketPriceRepository.delete_up_to`), and the next market-data sync refetches them — one extra
request per security, since fetching is range-based.

Two details carry the weight. `PRICE_RESTATING_ACTIONS` is a deliberate **subset** of
`SPLIT_LIKE_ACTIONS`: we fetch with `auto_adjust=False` and Yahoo rebases raw `Close` for splits only,
so `SPINOFF`/`STOCKDIV`/`ISSUECHANGE` are excluded as pure churn. And it fires **only for actions
newly inserted on this sync** (`CorporateActionRepository.existing_ib_keys()`) — the YTD statement
resends every action every time, so without that check all five daily jobs would wipe and refetch the
same history forever. Reported in `warnings[]` and as `prices_invalidated`.
Limitation: the 7-day jobs restore the current value, but the full history only comes back at the next
**08:00** 730-day `full_sync`. Tests: `tests/test_split_price_invalidation.py`.

---

## Tax report (Swiss framing)

`GET /api/tax/report?year=YYYY` and `.csv`. Switzerland doesn't tax private capital gains but does tax
dividend income and allows reclaiming foreign withholding via **DA-1** — so the report leads with
dividend income + withholding, then realized gains, then a year-end holdings snapshot (Steuerwert).

Two honesty flags, both badged in the UI and CSV:
- `dividend_source`: `ibkr` (real withholding) vs `yfinance_estimate` (gross guess, no withholding).
  Decided **per requested year** (`has_ibkr_dividends(start, end)`), never globally: a YTD Flex Query
  can't carry a prior year's cash transactions, so a global check made 2025 filter to `ibkr`, match
  nothing and report **0.00 labelled authoritative**. The two sources are never summed.
- `realized_source`: `trades` (IBKR FIFO) vs `closed_lot_estimate` (market price at close date — was
  ~8% off on a spot check, hence the badge)

**Steuerwert is valued at 31 December**, not today: `holdings_snapshot_as_of()` rebuilds the holdings
for `holdings_as_of` (= 31 Dec for a past year, today for the current one) using the same
`open_date`/`close_date` window as `_calculate_daily_value`, so it can't disagree with the portfolio
timeline. Positions with no resolvable price near that date are **omitted**, not counted as zero.

Frontend: `TaxTab.tsx`. It's a filing aid, not tax advice.

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
(`widen_cash_flows_covered_from`), so a later YTD statement can't shrink what a prior-year import
established. It must be the period start, not the first deposit's date: a covered week with no deposits is
still covered, and using the first row would hand that week's purchases to the lot side *and* count its
deposits.

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
lot is either still open or was released. Tests: `tests/test_contributions.py`,
`tests/test_cash_flow_ingest.py`.

---

## Sync schedule (Europe/Berlin)

| Time | Job | Touches Yahoo? |
|---|---|---|
| 08:00 | `full_sync_job` — IBKR + FX + 730d market data + dividends | **yes** |
| 13:00 | `ibkr_only_sync_job` — IBKR + FX | no |
| 15:00 | `market_data_only_sync_job` (7d) | yes |
| 20:00 | `ibkr_only_sync_job` — IBKR + FX | no |
| 22:00 | `market_data_only_sync_job` (7d) | yes |

The 13:00/20:00 IBKR-only jobs exist because a transient `Code=1001` at 08:00 used to cost a full day of
freshness. They deliberately **skip** market data and yfinance dividends — see rule 1. Pinned by
`tests/test_scheduler_jobs.py`. Status: `GET /api/scheduler/status`.

**A price that never arrives is otherwise silent.** `portfolio_service` values a position with no price
at **0.00** and moves on, so deleting SBI's poisoned prices took 446.93 CHF off the total with nothing
reporting it. `find_stale_priced_securities()` now runs after every market-data sync and warns when a
security **with open lots** has no cached price at all, or none newer than `STALE_PRICE_DAYS` (5 —
enough to absorb a weekend plus a holiday). Closed-out holdings are excluded: they legitimately stop
getting prices, and warning on them would be permanent noise.

`_collect_warnings()` hoists each step's warnings to the top of the job's result, because `_record_run`
reads `result["warnings"]` and a job's own dict never had that key — so warnings were being buried in
`details` and never rendered as warnings.

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

A **cloud routine** `ibkr-sync-validator` (claude.ai/code/routines) runs daily at 07:45 UTC to validate
the morning sync via the public API + the IBKR MCP connector. It **cannot SSH**, so it opens PRs rather
than pushing to `main`.

---

## Local development

```bash
cd backend && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev          # http://localhost:5173
```

Tests (159, all offline — no IBKR, Yahoo or FX-provider calls):
```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q
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
  whole recovery in one step: drop the prices the bad mapping produced and let a scheduled job refill
  them — incremental caching fetches only missing dates, so it costs **no ad-hoc Yahoo call**.
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
| A position's value is far off IBKR's | Suspect the `ticker_mappings` row before the price feed: run `manage_mappings list` and look for a currency disagreement, then compare `market_prices.close_price` against IBKR's `market_price` in the *same* currency |
| App total ≠ IBKR total | Compare against `gross_position_value`, **not** net liquidation (which adds cash); and intraday the app holds the last *close* while IBKR quotes live |
| Site "down" in the browser | Often TIM home DNS, not the server — verify with `Test-NetConnection`, not `nslookup` |
| Deploy says health FAILED | Usually the premature check; re-curl `/health` after ~15s |

---

## Current state (2026-07-28)

**40 securities, 36 open positions, 975 open tax lots, 67 trades, 62,178.99 CHF.** The 27 Jul
statement was ingested **offline** from a browser download (`ibkr_manual_xml`, 04:16 UTC) rather than
waiting on the Flex API, because three consecutive IBKR jobs had returned a plain `1001`. That is the
escape hatch working as designed: no token spend, no `1025` exposure, and `full_sync` re-ingesting the
same statement afterwards is idempotent.

`taxlots_skipped: 0`, `prices_invalidated: 0`, no "unsupported currencies" warning, and
`find_stale_priced_securities()` returns empty — every held security has a current price.

**The external cash ledger is live and verified against a real export.** The Flex Query now carries
Deposits & Withdrawals (at **Detail**) and the **Transfers** section (at **Transfer** level, not Lot —
Lot would emit a row per transferred lot and bury the cash leg in the list that has to be audited).
`App_OpenLots (7).xml` ingested **47 cash flows = 25 deposits + 22 in-kind transfers**, 0 skipped, and
**0 reclassified** — correct, because the transfer carried no cash (see the contributions section).
No manual reclassification was needed, so the automatic guard has never had to fire on this account.

`deposits_from` lands a few days *before* the transfer date, so the ledger genuinely starts at the
account's first funding. The set includes one real withdrawal (negative amount, sign preserved) and one
CHF deposit against an otherwise-EUR ledger, which is what exercises the FX path end to end. Note IBKR
sends the **legacy** `type="Deposits/Withdrawals"` spelling, not `"Deposits & Withdrawals"` — ibflex maps
both to `CashAction.DEPOSITWITHDRAW`, so nothing special is needed, but don't "fix" the enum comparison
if that string looks wrong.

`coverage_from` = the statement period start (1 Jan of the current year, since the query is YTD), so
all-time and 12M are `spliced` while 6M and 3M run on **deposits alone** and are already rotation-proof.
Where both sources overlap they agree to within **~12%** — two independent derivations (lot cost basis
vs. the cash ledger) landing that close is the best available evidence that the pre-ledger lot-based
figures were sound. `Σ monthly[].net_eur` matches total cost basis **to the cent**, which is the identity
check described in the contributions section.

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

Dividends: 57 cash-transaction rows → 26 IBKR dividend payments (43.31 gross / 7.00 withholding /
36.31 net EUR). 2026 reports `dividend_source='ibkr'` and `realized_source='trades'`; realized
−105.40 EUR over 4 closed lots. The tax report's `holdings_snapshot_total` matches the portfolio
summary to the cent, which is the shared-code guarantee holding.

**Reconciled against IBKR to 0.12%** on 2026-07-27. Compare the app against `gross_position_value`,
never net liquidation (which adds cash and accrued dividends) — "buying power" is a margin metric
derived from that same cash, not a separate bucket.

Cross-checked against IBKR via the MCP connector: IBKR lists **282 YTD trades = 218 `CASH`** (FX
conversions, correctly filtered out) **+ 64 `STK`**, and the 64 match ours symbol-for-symbol. Same-day,
same-price pairs (e.g. NU 7 @ 17.205 twice on 2026-02-04) are **genuine separate fills**, not duplicates.

**Prior years remain estimates** — a YTD query can't reach them. Backfilling 2025 needs a one-off period
change in the Flex Query (see the tax section); until then 2025 correctly reports
`dividend_source='yfinance_estimate'`.
