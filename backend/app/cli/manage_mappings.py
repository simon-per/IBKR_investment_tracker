"""
Inspect and edit the IBKR -> Yahoo ticker mappings.

`ticker_mappings` decides where every price comes from, and it was the last production
table still edited by hand-written SQL over ssh — no validation, no audit trail, and a
typo that mis-prices a position looks exactly like a real price. That is not theoretical:
an auto-discovered `SBI/TSE -> SBI` row pointed a Toronto CAD holding at an unrelated US
fund and carried it 61% high for months, and because tier 1 of the lookup is this table,
the row kept shadowing the (correct) suffix logic even after that logic was fixed.

So this is the third CLI in the same pattern as `ingest_flex_xml` and `import_prices`,
for the same reason: `/api/` is proxied publicly and unauthenticated, and a route that
redirects where prices come from is a far larger surface than a command over ssh.

Touches no network — mappings only decide what a *later* sync will fetch.

    python -m app.cli.manage_mappings list
    python -m app.cli.manage_mappings set 2330 TWSE 2330.TW --notes "TSMC, Taiwan"
    python -m app.cli.manage_mappings disable SBI TSE --purge-prices

`list` puts the security's currency next to the one its Yahoo ticker implies, because a
disagreement between those two columns *is* the bug above. `disable --purge-prices` is
the documented recovery in one step: stop consulting the mapping and drop the prices it
produced, then let a scheduled job refill them (incremental caching fetches only missing
dates, so this costs no ad-hoc Yahoo call).
"""
import argparse
import asyncio
import logging
import sys
from app.clock import utcnow
from types import SimpleNamespace
from typing import Optional, Tuple

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.dividend_payment import DividendPayment
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.models.ticker_mapping import TickerMapping
from app.repositories.dividend_repository import DividendRepository
from app.repositories.market_price_repository import MarketPriceRepository
from app.repositories.sync_run_repository import SyncRunRepository
from app.repositories.ticker_mapping_repository import TickerMappingRepository
from app.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

SYNC_TYPE = "manual_mapping"


class MappingError(Exception):
    """A refused edit — reported, never half-applied."""


def implied_currency(service: MarketDataService, yahoo_ticker: str) -> Optional[str]:
    """
    The currency a Yahoo ticker implies on its own, or None if it implies nothing.

    Reuses `MarketDataService._get_currency_from_ticker` with a security that has no
    currency of its own, so the answer comes from the same override table and suffix map
    the fetch path uses and the two cannot drift apart. A bare ticker legitimately
    returns None: `AMZN` says nothing about its currency.
    """
    return service._get_currency_from_ticker(yahoo_ticker, SimpleNamespace(currency=None))


async def _find_security(db, symbol: str, exchange: str) -> Optional[Security]:
    result = await db.execute(
        select(Security).where(Security.symbol == symbol, Security.exchange == exchange)
    )
    return result.scalars().first()


async def cmd_list(db) -> int:
    service = MarketDataService(db)

    mappings = list((await db.execute(
        select(TickerMapping).order_by(TickerMapping.ibkr_symbol, TickerMapping.ibkr_exchange)
    )).scalars().all())

    if not mappings:
        print("No ticker mappings.")
        return 0

    counts = dict((await db.execute(
        select(MarketPrice.security_id, func.count(MarketPrice.id))
        .group_by(MarketPrice.security_id)
    )).all())

    # Newest estimate row per security. A dividend row older than the mapping's
    # own updated_at was fetched under a *different* ticker — the SBI shape — so
    # showing the two side by side puts that where the mapping is read.
    newest_estimate = dict((await db.execute(
        select(DividendPayment.security_id, func.max(DividendPayment.last_computed))
        .where(DividendPayment.source == "yfinance_estimate")
        .group_by(DividendPayment.security_id)
    )).all())

    # sec/tkr side by side is the point: they must agree, or the mapping is pointing at
    # a different instrument than the security it claims to price.
    header = (
        f"{'id':>3}  {'IBKR':<18} {'Yahoo':<12} {'source':<8} "
        f"{'secCcy':<7} {'tkrCcy':<7} {'prices':>7} {'divAge':>7}  active"
    )
    print(header)
    print("-" * len(header))

    disagreements = []
    predating = []
    for m in mappings:
        security = await _find_security(db, m.ibkr_symbol, m.ibkr_exchange)
        sec_ccy = (security.currency if security else None) or "-"
        tkr_ccy = implied_currency(service, m.yahoo_ticker) or "-"
        n = counts.get(security.id, 0) if security else 0

        flag = ""
        if security and tkr_ccy != "-" and sec_ccy != tkr_ccy:
            flag = "  <-- CURRENCY DISAGREEMENT"
            disagreements.append((m, sec_ccy, tkr_ccy))

        div_age = "-"
        newest = newest_estimate.get(security.id) if security else None
        if newest is not None:
            div_age = f"{(utcnow() - newest).days}d"
            if m.updated_at and newest < m.updated_at:
                flag += "  <-- DIVIDENDS PREDATE MAPPING"
                predating.append((m, newest))

        print(
            f"{m.id:>3}  {m.ibkr_symbol + '@' + m.ibkr_exchange:<18} {m.yahoo_ticker:<12} "
            f"{(m.source or ''):<8} {sec_ccy:<7} {tkr_ccy:<7} {n:>7} {div_age:>7}  "
            f"{'yes' if m.is_active else 'NO'}{flag}"
        )

    if predating:
        print(
            f"\n{len(predating)} mapping(s) have dividend estimates older than the "
            f"mapping itself — those rows came from a different ticker and still drive "
            f"the forecast's cadence:"
        )
        for m, newest in predating:
            print(
                f"  {m.ibkr_symbol}@{m.ibkr_exchange}: newest estimate {newest:%Y-%m-%d}, "
                f"mapping updated {m.updated_at:%Y-%m-%d}. Clear with "
                f"`purge_dividend_estimates {m.ibkr_symbol} {m.ibkr_exchange}`"
            )

    if disagreements:
        print(
            f"\n{len(disagreements)} mapping(s) point at a ticker quoted in a different "
            f"currency than the security. That is how SBI@TSE was mispriced — the prices "
            f"are probably from a different instrument:"
        )
        for m, sec_ccy, tkr_ccy in disagreements:
            print(
                f"  {m.ibkr_symbol}@{m.ibkr_exchange} -> {m.yahoo_ticker}: "
                f"security is {sec_ccy}, ticker implies {tkr_ccy}. Fix with "
                f"`disable {m.ibkr_symbol} {m.ibkr_exchange} --purge-prices` then `set ...`"
            )
    else:
        print("\nNo currency disagreements.")
    return 0


async def cmd_set(
    db, symbol: str, exchange: str, yahoo_ticker: str,
    notes: Optional[str], dry_run: bool,
) -> Tuple[int, dict]:
    service = MarketDataService(db)
    security = await _find_security(db, symbol, exchange)
    tkr_ccy = implied_currency(service, yahoo_ticker)

    if security and tkr_ccy and security.currency and tkr_ccy != security.currency:
        raise MappingError(
            f"{yahoo_ticker} is quoted in {tkr_ccy} but {symbol}@{exchange} is a "
            f"{security.currency} security — refusing. A mapping to the wrong listing is "
            f"invisible downstream: the prices arrive, they are just the wrong company's"
        )

    if not security:
        # Legitimate and expected when pinning a mapping ahead of the statement that
        # first carries the security, so this informs rather than blocks.
        print(
            f"Note: no security matches {symbol}@{exchange} yet — the mapping is stored "
            f"and will apply as soon as one does."
        )
    elif not tkr_ccy and service._get_exchange_suffix(security):
        # The SBI shape: a foreign listing pointed at a suffix-less ticker, which on Yahoo
        # readily resolves to an unrelated US listing of the same symbol. Can't be refused
        # (a bare ticker implies nothing, and an operator may know better than the map),
        # but it should never be typed by accident.
        print(
            f"WARNING: {symbol}@{exchange} is a foreign listing (suffix "
            f"'{service._get_exchange_suffix(security)}') but {yahoo_ticker} has no suffix. "
            f"A bare ticker is how SBI@TSE ended up priced off a US fund — double-check "
            f"this is really the same instrument."
        )

    existing = await service.ticker_mapping_repo.get_mapping(symbol, exchange)
    before = existing.yahoo_ticker if existing else None

    # Changing the ticker retires whatever the old one produced. Prices are
    # obvious; dividend estimates are not, and they outlive the mapping silently —
    # that is the SBI failure exactly. Name them here, at the moment they become
    # suspect, because nothing downstream will.
    stale_estimates = 0
    if security and before and before != yahoo_ticker:
        stale_estimates = len(
            await DividendRepository(db).get_estimates_for_security(security.id)
        )
        if stale_estimates:
            print(
                f"WARNING: {stale_estimates} yfinance dividend estimate(s) for "
                f"{symbol}@{exchange} were fetched under {before} and are now suspect. "
                f"They still drive the forecast's cadence. Clear them with "
                f"`python -m app.cli.purge_dividend_estimates {symbol} {exchange}`."
            )

    if dry_run:
        print(
            f"DRY RUN - would {'update' if existing else 'create'} "
            f"{symbol}@{exchange} -> {yahoo_ticker}"
            + (f" (was {before})" if before else "")
        )
        return 0, {}

    await service.ticker_mapping_repo.upsert_mapping(
        ibkr_symbol=symbol, ibkr_exchange=exchange, yahoo_ticker=yahoo_ticker,
        source="manual", notes=notes,
    )
    await db.commit()
    print(
        f"{'Updated' if existing else 'Created'} {symbol}@{exchange} -> {yahoo_ticker}"
        + (f" (was {before})" if before and before != yahoo_ticker else "")
    )
    return 0, {
        "action": "set", "symbol": symbol, "exchange": exchange,
        "yahoo_ticker": yahoo_ticker, "previous": before,
    }


async def cmd_disable(
    db, symbol: str, exchange: str, purge_prices: bool, dry_run: bool,
) -> Tuple[int, dict]:
    repo = TickerMappingRepository(db)
    mapping = await repo.get_mapping(symbol, exchange)
    if not mapping:
        raise MappingError(f"No active mapping for {symbol}@{exchange}")

    security = await _find_security(db, symbol, exchange)
    price_count = 0
    estimate_count = 0
    if purge_prices:
        if not security:
            raise MappingError(
                f"--purge-prices needs a security to purge, and none matches "
                f"{symbol}@{exchange}"
            )
        price_count = await MarketPriceRepository(db).count_by_security(security.id)
        # Dividend estimates are derived from the SAME Yahoo ticker, so a mapping
        # that produced wrong prices produced wrong dividends too. Purging only
        # prices is what left SBI's two poisoned rows behind to define a gold
        # miner's payout schedule for a month after the mapping was corrected.
        estimate_count = len(
            await DividendRepository(db).get_estimates_for_security(security.id)
        )

    if dry_run:
        print(
            f"DRY RUN - would disable {symbol}@{exchange} -> {mapping.yahoo_ticker}"
            + (f" and delete {price_count} cached price(s) and {estimate_count} "
               f"dividend estimate(s)" if purge_prices else "")
        )
        return 0, {}

    # Soft delete: get_mapping() already filters on is_active, so the row stops being
    # consulted while the record of what was tried survives.
    mapping.is_active = False
    await db.flush()

    deleted = 0
    dividends_deleted = 0
    if purge_prices:
        deleted = await MarketPriceRepository(db).delete_all_for_security(security.id)
        dividends_deleted = await DividendRepository(db).delete_estimates_for_security(
            security.id
        )
    await db.commit()

    print(f"Disabled {symbol}@{exchange} -> {mapping.yahoo_ticker}")
    if purge_prices:
        print(
            f"Deleted {deleted} cached price(s) and {dividends_deleted} dividend "
            f"estimate(s) for security {security.id}. IBKR dividend rows are kept — "
            f"they carry real withholding and no mapping can invalidate them. A "
            f"scheduled job will refill both — do not fetch by hand (CLAUDE.md rule 1)."
        )
    return 0, {
        "action": "disable", "symbol": symbol, "exchange": exchange,
        "yahoo_ticker": mapping.yahoo_ticker, "prices_deleted": deleted,
        "dividend_estimates_deleted": dividends_deleted,
    }


async def run(args) -> int:
    started_at = utcnow()

    async with AsyncSessionLocal() as db:
        try:
            if args.command == "list":
                return await cmd_list(db)

            if args.command == "set":
                code, details = await cmd_set(
                    db, args.symbol, args.exchange, args.yahoo_ticker,
                    args.notes, args.dry_run,
                )
            else:
                code, details = await cmd_disable(
                    db, args.symbol, args.exchange, args.purge_prices, args.dry_run,
                )

        except Exception as e:
            await db.rollback()
            # Best-effort bookkeeping, as in the other CLIs: it must never mask the error.
            await SyncRunRepository(db).record(
                sync_type=SYNC_TYPE, status="error", message=str(e), started_at=started_at,
            )
            print(f"FAILED - nothing was changed: {e}", file=sys.stderr)
            return 1

        if details:
            # A mapping change being invisible is why SBI went unnoticed for months, so
            # every edit lands in the same history the syncs report to.
            await SyncRunRepository(db).record(
                sync_type=SYNC_TYPE,
                status="success",
                message=(
                    f"{details['action']} {details['symbol']}@{details['exchange']} "
                    f"-> {details['yahoo_ticker']}"
                ),
                details=details,
                started_at=started_at,
            )
        return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show every mapping with its currency check")

    p_set = sub.add_parser("set", help="Create or update a mapping (source=manual)")
    p_set.add_argument("symbol", help="IBKR symbol, e.g. 2330")
    p_set.add_argument("exchange", help="IBKR exchange, e.g. TWSE")
    p_set.add_argument("yahoo_ticker", help="Yahoo ticker, e.g. 2330.TW")
    p_set.add_argument("--notes", default=None, help="Why this mapping exists")
    p_set.add_argument("--dry-run", action="store_true")

    p_del = sub.add_parser("disable", help="Stop using a mapping (keeps the row)")
    p_del.add_argument("symbol")
    p_del.add_argument("exchange")
    p_del.add_argument(
        "--purge-prices", action="store_true",
        help="Also delete the security's cached prices, which a wrong mapping poisoned",
    )
    p_del.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
