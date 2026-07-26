"""
Sync Helper
Shared tax lot reconciliation logic used by both sync.py router and scheduler_service.py.

Instead of deleting ALL tax lots on sync (losing history of sold positions),
this module:
1. Snapshots existing open lots (grouped per security)
2. Deletes only open lots
3. Creates new lots from IBKR data
4. Detects sold positions by comparing the total quantity held per security
   (snapshot vs incoming), NOT by matching individual lot prices
5. Creates closed lot records (FIFO) for the sold quantity

Why quantity-based reconciliation:
A genuine sale reduces the number of shares held. A corporate action (e.g. the
S&P Global -> Mobility Global spinoff) makes IBKR re-allocate the per-share cost
basis for days afterwards, so ``costBasisPrice`` drifts daily without any sale.
Matching lots on price therefore produced phantom "closed" lots on every drift
day. Comparing total quantity per security is immune to that drift.
"""
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional, Set

from sqlalchemy import and_, select

from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.trade import Trade
from app.services.currency_service import CurrencyService
from app.services.ibkr_service import IBKRService
from app.repositories.taxlot_repository import TaxLotRepository
from app.repositories.trade_repository import TradeRepository
from app.repositories.corporate_action_repository import CorporateActionRepository

logger = logging.getLogger(__name__)


async def ingest_flex_statement(db, flex_data: Dict) -> Dict:
    """
    Apply one parsed Flex statement to the database, and nothing else.

    This is the whole post-download half of a sync: securities -> transaction history ->
    dividends -> tax lot reconciliation -> bookkeeping. It was duplicated almost verbatim
    in `routers/sync.py` and `scheduler_service.py`; the offline XML ingest
    (`app/cli/ingest_flex_xml.py`) would have made it a third copy, and three copies of
    the reconciliation order is how the views drift apart.

    Deliberately does **no** network I/O and does **not** commit — the caller owns the
    transaction, so a failure anywhere here leaves the database untouched. Currency
    conversion reads the cached `exchange_rates` table via CurrencyService.

    Raises EmptyStatementError (from reconcile_taxlots) if the statement has no tax lots
    while the database still holds open ones — the wipe guard, which every caller must
    keep getting for free.
    """
    # Imported here rather than at module scope to match the existing pattern and keep
    # sync_helper importable from the CLI without pulling in the service graph eagerly.
    from app.services.dividend_service import DividendService
    from app.services.benchmark_service import BenchmarkService
    from app.repositories.security_repository import SecurityRepository
    from app.repositories.taxlot_repository import TaxLotRepository
    from app.repositories.app_settings_repository import AppSettingsRepository

    ibkr_service = IBKRService()
    currency_service = CurrencyService(db)
    security_repo = SecurityRepository(db)
    taxlot_repo = TaxLotRepository(db)
    trade_repo = TradeRepository(db)
    corp_action_repo = CorporateActionRepository(db)
    app_settings = AppSettingsRepository(db)

    # Securities first: everything downstream is keyed on conid -> security_id.
    securities_data = await ibkr_service.extract_securities(flex_data)
    conid_to_security_id: Dict[str, int] = {}
    for sec_data in securities_data:
        security = await security_repo.upsert(sec_data)
        conid_to_security_id[sec_data['conid']] = security.id
    logger.info(f"Synced {len(conid_to_security_id)} securities")

    # Authoritative transaction history. Tolerant of absent Flex sections, and additive:
    # it records history without moving any lot on its own.
    trades_data = await ibkr_service.extract_trades(flex_data)
    corp_actions_data = await ibkr_service.extract_corporate_actions(flex_data)
    await persist_transactions(
        trade_repo, corp_action_repo, conid_to_security_id,
        trades_data, corp_actions_data,
    )

    # Real dividend income (gross/withholding/net) from <CashTransactions>. Flex-only.
    cash_txns = await ibkr_service.extract_cash_transactions(flex_data)
    await DividendService(db).sync_dividends_from_cash_transactions(
        cash_txns, conid_to_security_id
    )

    last_sync_date = await app_settings.get_last_sync_to_date()
    taxlots_data = await ibkr_service.extract_taxlots(flex_data)

    recon = await reconcile_taxlots(
        taxlot_repo=taxlot_repo,
        currency_service=currency_service,
        conid_to_security_id=conid_to_security_id,
        taxlots_data=taxlots_data,
        report_to_date=flex_data['to_date'],
        trade_repo=trade_repo,
        corp_action_repo=corp_action_repo,
        last_sync_date=last_sync_date,
    )

    # Remember this statement's to_date as the next sync's window start.
    if flex_data.get('to_date'):
        await app_settings.set_last_sync_to_date(flex_data['to_date'])

    # Tax lots moved, so any cached benchmark timeline is stale.
    cleared = await BenchmarkService(db).clear_cache()
    logger.info(f"Cleared {cleared} benchmark timeline cache entries (tax lots changed)")

    warnings: List[str] = []
    if recon["skipped_currencies"]:
        warnings.append(
            f"Skipped {recon['taxlots_skipped']} taxlot(s) with unsupported currencies: "
            f"{', '.join(sorted(recon['skipped_currencies']))}"
        )
    warnings.extend(flex_data.get('flex_warnings') or [])

    return {
        "securities_synced": len(conid_to_security_id),
        "taxlots_synced": recon["taxlots_synced"],
        "taxlots_skipped": recon["taxlots_skipped"],
        "lots_closed_full": recon["lots_closed_full"],
        "lots_closed_partial": recon["lots_closed_partial"],
        "lots_restamped": recon["lots_restamped"],
        "trades_seen": len(trades_data),
        "corporate_actions_seen": len(corp_actions_data),
        "cash_transactions_seen": len(cash_txns),
        "total_cost_basis_eur": float(recon["total_cost_basis_eur"]),
        "account_id": flex_data['account_id'],
        "data_from": str(flex_data['from_date']) if flex_data['from_date'] else None,
        "data_to": str(flex_data['to_date']) if flex_data['to_date'] else None,
        "warnings": warnings,
    }


async def persist_transactions(
    trade_repo: TradeRepository,
    corp_repo: CorporateActionRepository,
    conid_to_security_id: Dict[str, int],
    trades_data: List[Dict],
    corp_actions_data: List[Dict],
) -> Dict:
    """
    Idempotently upsert parsed IBKR <Trades> and <CorporateActions> rows.

    Additive and side-effect-free with respect to reconciliation: this only
    records the authoritative transaction history. ``security_id`` is resolved
    from ``conid`` when the security exists locally (nullable otherwise, e.g. a
    security we have never held). Tolerant of empty inputs (the Flex Query may
    not yet emit these sections).
    """
    # IBKR conid arrives as an int in conid_to_security_id but our parsers store
    # it as a string; normalize the map to string keys so resolution is reliable.
    conid_map = {str(k): v for k, v in conid_to_security_id.items()}

    # That map is built from the statement's OpenPositions, so a security sold out
    # completely has dropped off it — which left every SELL trade unlinked even though
    # the security row was still sitting in the DB. Fill the gaps from the DB in one
    # query, keyed on the same conid the statement uses.
    unresolved = {
        str(row["conid"])
        for row in list(trades_data) + list(corp_actions_data)
        if row.get("conid") is not None and str(row["conid"]) not in conid_map
    }
    if unresolved:
        result = await trade_repo.session.execute(
            select(Security.id, Security.conid).where(
                Security.conid.in_([int(c) for c in unresolved if str(c).isdigit()])
            )
        )
        recovered = {str(conid): sec_id for sec_id, conid in result.all()}
        if recovered:
            logger.info(
                f"Resolved {len(recovered)} conid(s) from the database that were absent "
                f"from this statement's open positions (fully-sold securities)"
            )
        conid_map.update(recovered)

    trades_saved = 0
    for t in trades_data:
        data = dict(t)
        data["security_id"] = conid_map.get(str(t["conid"]))
        await trade_repo.upsert(data)
        trades_saved += 1

    corp_saved = 0
    for ca in corp_actions_data:
        data = dict(ca)
        data["security_id"] = conid_map.get(str(ca["conid"]))
        await corp_repo.upsert(data)
        corp_saved += 1

    if trades_saved or corp_saved:
        logger.info(f"Persisted {trades_saved} trade(s) and {corp_saved} corporate action(s)")
    return {"trades_saved": trades_saved, "corporate_actions_saved": corp_saved}


class EmptyStatementError(Exception):
    """
    Raised when an IBKR sync yields zero incoming tax lots while the database
    still holds open positions. This is almost always a failed/partial Flex
    statement (successful-but-empty response, timeout, throttle) rather than a
    genuine full liquidation, so we refuse to delete every open lot. Callers
    should treat this as a transient failure and leave existing data untouched.
    """


# When the share count of a security drops between syncs, distinguish a real sale
# from a reverse split / share consolidation: a sale reduces total cost basis,
# whereas a split conserves it (fewer shares, higher price, same money). If the
# incoming cost basis is at least this fraction of the snapshot cost basis, the
# drop is treated as a corporate action, not a sale. The 1% band also absorbs
# reverse-split cash-in-lieu of fractional shares.
COST_CONSERVED_RATIO = Decimal("0.99")

# Corporate-action types that change a holding's share count WITHOUT being a
# taxable disposal (so a matching quantity drop must not be recorded as a sale).
# Mergers / tenders ARE disposals and deliberately excluded — they fall through
# to the sale path. Values are ibflex Reorg enum names (see ibkr_service parser).
SPLIT_LIKE_ACTIONS = {
    "FORWARDSPLIT", "FORWARDSPLITISSUE",
    "REVERSESPLIT",
    "SPINOFF", "CONTRACTSPINOFF",
    "STOCKDIV",
    "ISSUECHANGE",
    "CONTRACTCONSOLIDATION", "CONTRACTSPLIT",
}


async def reconcile_taxlots(
    taxlot_repo: TaxLotRepository,
    currency_service: CurrencyService,
    conid_to_security_id: Dict[str, int],
    taxlots_data: List[Dict],
    report_to_date,
    trade_repo=None,
    corp_action_repo=None,
    last_sync_date=None,
) -> Dict:
    """
    Reconcile incoming IBKR tax lots against existing open lots.

    Preserves closed lot history and detects newly sold positions by comparing
    the total quantity held per security (snapshot vs incoming).

    When ``trade_repo``/``corp_action_repo`` and ``last_sync_date`` are provided,
    a detected share-count drop is classified against the authoritative IBKR data
    for the window (last_sync_date, report_to_date]:
      * a split-like corporate action (split/reverse-split/spinoff/symbol change)
        suppresses the phantom sale deterministically;
      * a real SELL trade stamps the closed lot with close_source='trade' and the
        trade's actual date.
    Absent that data (Flex Query not yet updated / first sync), it falls back to
    the window-free cost-conservation heuristic (close_source='heuristic').

    Args:
        taxlot_repo: TaxLotRepository instance
        currency_service: CurrencyService instance
        conid_to_security_id: Map of IBKR conid -> database security_id
        taxlots_data: List of tax lot dicts from ibkr_service.extract_taxlots()
        report_to_date: The to_date from the flex report (used as close_date for sold lots)
        trade_repo: optional TradeRepository for trade-driven classification
        corp_action_repo: optional CorporateActionRepository for deterministic reclassification
        last_sync_date: optional to_date of the previous sync (window start)

    Returns:
        Dict with counts: taxlots_synced, taxlots_skipped, skipped_currencies,
                          lots_closed_full, lots_closed_partial, total_cost_basis_eur
    """
    taxlots_count = 0
    taxlots_skipped = 0
    skipped_currencies: Set[str] = set()
    total_cost_basis_eur = Decimal("0")
    lots_closed_full = 0
    lots_closed_partial = 0

    # --- Phase A: Snapshot existing open lots, grouped per security ---
    # Include securities with open lots in the DB but not in the incoming query
    # (fully-sold securities), so they get reconciled into closed lots.
    # Grouping into a list (not a price-keyed dict) preserves multiple distinct
    # lots that share the same (security_id, open_date, price).
    snapshot: Dict[int, List[Dict]] = defaultdict(list)
    existing_open_lots = await taxlot_repo.get_open_taxlots()

    # --- Guard: refuse to wipe the portfolio on an empty/failed statement ---
    # Phase B below deletes every open lot before recreating from incoming data.
    # If the incoming set is empty while we still hold open positions, this is
    # almost certainly a failed or partial Flex statement (successful-but-empty
    # body, network timeout, throttle), NOT a genuine full liquidation. Aborting
    # here — before any delete — leaves existing data intact. A real liquidation
    # is instead evidenced by SELL trades once <Trades> parsing is enabled.
    if not taxlots_data and existing_open_lots:
        raise EmptyStatementError(
            f"IBKR sync returned 0 tax lots but {len(existing_open_lots)} open "
            f"lot(s) exist; treating as a failed statement and refusing to delete."
        )

    all_security_ids = set(conid_to_security_id.values()) | {
        lot.security_id for lot in existing_open_lots
    }

    for security_id in all_security_ids:
        open_lots = await taxlot_repo.get_by_security_id(security_id, is_open=True)
        for lot in open_lots:
            snapshot[security_id].append({
                "quantity": lot.quantity,
                "cost_basis_eur": lot.cost_basis_eur,
                "cost_basis": lot.cost_basis,
                "currency": lot.currency,
                "security_id": lot.security_id,
                "open_date": lot.open_date,
                "price_per_unit": lot.price_per_unit,
            })

    snapshot_lot_count = sum(len(lots) for lots in snapshot.values())
    logger.info(f"Snapshot: {snapshot_lot_count} existing open lots across {len(snapshot)} securities")

    # --- Phase B: Delete existing OPEN lots only (preserves closed lots) ---
    for security_id in all_security_ids:
        await taxlot_repo.delete_open_by_security_id(security_id)

    # --- Phase C: Create new lots from IBKR data, track incoming quantity + cost per security ---
    incoming_qty: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    incoming_cost: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))

    for lot_data in taxlots_data:
        conid = lot_data["conid"]
        security_id = conid_to_security_id.get(conid)
        if not security_id:
            logger.warning(f"Security with conid {conid} not found, skipping taxlot")
            taxlots_skipped += 1
            continue

        # Convert cost basis to EUR
        try:
            cost_basis_eur = await currency_service.convert_to_eur(
                amount=lot_data["cost_basis"],
                from_currency=lot_data["currency"],
                target_date=lot_data["open_date"],
            )
        except ValueError as e:
            logger.warning(
                f"Skipping taxlot with unsupported currency {lot_data['currency']}: {e}"
            )
            skipped_currencies.add(lot_data["currency"])
            taxlots_skipped += 1
            continue

        taxlot_data = {
            "security_id": security_id,
            "open_date": lot_data["open_date"],
            "quantity": lot_data["quantity"],
            "cost_basis": lot_data["cost_basis"],
            "price_per_unit": lot_data["price_per_unit"],
            "currency": lot_data["currency"],
            "cost_basis_eur": cost_basis_eur,
            "is_open": lot_data["is_open"],
        }

        await taxlot_repo.create(taxlot_data)
        taxlots_count += 1
        total_cost_basis_eur += cost_basis_eur
        incoming_qty[security_id] += lot_data["quantity"]
        incoming_cost[security_id] += lot_data["cost_basis"]

    # --- Phase D: Reconcile — detect sold positions by quantity drop per security ---
    # A sale is a reduction in shares held. Price drift (corporate actions) does
    # not change quantity, so it never triggers a closure here. Sold quantity is
    # attributed FIFO (oldest open_date first) across the snapshot lots.
    close_date = report_to_date

    # Resolve conid for every snapshot security so we can look up its trades /
    # corporate actions (the incoming map only covers still-held securities).
    security_id_to_conid: Dict[int, str] = {}
    if snapshot and (trade_repo is not None or corp_action_repo is not None):
        rows = (await taxlot_repo.session.execute(
            select(Security.id, Security.conid).where(Security.id.in_(list(snapshot.keys())))
        )).all()
        security_id_to_conid = {sid: str(conid) for sid, conid in rows if conid is not None}

    for security_id, snap_lots in snapshot.items():
        snapshot_qty = sum((lot["quantity"] for lot in snap_lots), Decimal("0"))
        sold_qty = snapshot_qty - incoming_qty.get(security_id, Decimal("0"))

        if sold_qty <= 0:
            # No net reduction: unchanged holding, a buy, forward split, or pure price drift.
            continue

        conid = security_id_to_conid.get(security_id)

        # (1) Deterministic corporate-action reclassification. If a split-like
        # action (split/reverse-split/spinoff/symbol change) occurred for this
        # security in the window since the last sync, the share-count change is
        # NOT a sale — refresh the open lots and record no closure.
        if conid and corp_action_repo is not None and last_sync_date is not None:
            actions = await corp_action_repo.get_by_conid_in_range(conid, last_sync_date, report_to_date)
            if any((a.action_type or "") in SPLIT_LIKE_ACTIONS for a in actions):
                types = ",".join(sorted({a.action_type for a in actions if a.action_type}))
                logger.info(
                    f"security_id={security_id}: qty dropped {sold_qty} but a split-like "
                    f"corporate action ({types}) occurred — reclassifying, not a sale"
                )
                continue

        # (2) Window-free fallback heuristic: a reverse split / consolidation
        # conserves total cost basis (fewer shares, higher price, same money);
        # a real sale reduces it. If cost basis is (near) conserved, don't record a sale.
        snapshot_cost = sum((lot["cost_basis"] for lot in snap_lots), Decimal("0"))
        inc_cost = incoming_cost.get(security_id, Decimal("0"))
        if snapshot_cost > 0 and inc_cost >= snapshot_cost * COST_CONSERVED_RATIO:
            logger.info(
                f"security_id={security_id}: qty dropped {sold_qty} but cost basis "
                f"conserved ({inc_cost}/{snapshot_cost}) — split/consolidation, not a sale"
            )
            continue

        # (3) It's a real sale. Prefer the actual SELL trade's date + a 'trade'
        # provenance tag when trade data is available for the window; otherwise
        # fall back to the report date and mark the closure 'heuristic'.
        close_source = "heuristic"
        effective_close_date = close_date
        if conid and trade_repo is not None and last_sync_date is not None:
            trades = await trade_repo.get_by_conid_in_range(conid, last_sync_date, report_to_date)
            sell_dates = [t.trade_date for t in trades if (t.buy_sell or "").upper() == "SELL"]
            if sell_dates:
                close_source = "trade"
                effective_close_date = max(sell_dates)

        if not effective_close_date:
            # No date to stamp the closure with — skip creating closed lots.
            logger.warning(
                f"Sold {sold_qty} shares of security_id={security_id} but no "
                f"close date available; skipping closed-lot creation"
            )
            continue

        remaining = sold_qty
        for lot in sorted(snap_lots, key=lambda l: l["open_date"]):
            if remaining <= 0:
                break
            take = min(lot["quantity"], remaining)
            if take <= 0:
                continue

            proportion = take / lot["quantity"]
            sold_cost_eur = lot["cost_basis_eur"] * proportion
            sold_cost = lot["cost_basis"] * proportion

            closed_data = {
                "security_id": lot["security_id"],
                "open_date": lot["open_date"],
                "quantity": take,
                "cost_basis": sold_cost,
                "price_per_unit": lot["price_per_unit"],
                "currency": lot["currency"],
                "cost_basis_eur": sold_cost_eur,
                "is_open": False,
                "close_date": effective_close_date,
                "close_source": close_source,
            }
            await taxlot_repo.create(closed_data)

            if take == lot["quantity"]:
                lots_closed_full += 1
            else:
                lots_closed_partial += 1
            logger.info(
                f"Closed lot (FIFO): security_id={lot['security_id']}, "
                f"open_date={lot['open_date']}, sold_qty={take}, "
                f"close_date={effective_close_date}, source={close_source}"
            )
            remaining -= take

        if remaining > 0:
            # Snapshot didn't hold enough shares to cover the reported drop.
            # This shouldn't happen; log it for visibility rather than silently drop.
            logger.warning(
                f"Reconcile: security_id={security_id} sold_qty exceeded snapshot "
                f"by {remaining}; closed lots may understate the sale"
            )

    # --- Phase E: adopt real sale dates for lots closed before <Trades> existed ---
    lots_restamped = await restamp_unsourced_closed_lots(taxlot_repo, trade_repo)

    logger.info(
        f"Reconciliation: {taxlots_count} synced, {lots_closed_full} fully closed, "
        f"{lots_closed_partial} partially closed, {taxlots_skipped} skipped"
    )

    return {
        "taxlots_synced": taxlots_count,
        "taxlots_skipped": taxlots_skipped,
        "skipped_currencies": skipped_currencies,
        "lots_closed_full": lots_closed_full,
        "lots_closed_partial": lots_closed_partial,
        "lots_restamped": lots_restamped,
        "total_cost_basis_eur": total_cost_basis_eur,
    }


async def restamp_unsourced_closed_lots(
    taxlot_repo: TaxLotRepository,
    trade_repo: Optional[TradeRepository],
) -> int:
    """
    Give a real sale date to lots that were closed before trade data existed.

    Lots closed by the fallback heuristic carry the *sync* date they were noticed on
    rather than the date they actually sold, and no ``close_source``. Once <Trades> is
    ingested the truth is available, but Phase D only stamps lots it closes on this run —
    so those older lots would keep a wrong date forever (CRM and NFLX both read
    2026-04-17 when they actually sold on 2026-03-13).

    A lot is only re-stamped when the match is unambiguous:
      * exactly one SELL trade for that security has |quantity| equal to the lot's, and
      * that trade is not newer than the recorded close date (the heuristic date is when
        the drop was *detected*, so the real sale can only be earlier or the same day).

    Anything less certain is left alone — a wrong date is better than a confidently wrong
    one. Idempotent: a stamped lot has a ``close_source`` and is never revisited.
    """
    if trade_repo is None:
        return 0

    unsourced = (await taxlot_repo.session.execute(
        select(TaxLot).where(
            and_(
                TaxLot.is_open == False,  # noqa: E712 - SQL comparison, not identity
                TaxLot.close_source.is_(None),
                TaxLot.security_id.isnot(None),
            )
        )
    )).scalars().all()
    if not unsourced:
        return 0

    sells_by_security: Dict[int, List] = defaultdict(list)
    rows = (await trade_repo.session.execute(
        select(Trade).where(Trade.security_id.isnot(None))
    )).scalars().all()
    for trade in rows:
        if (trade.buy_sell or "").upper() == "SELL":
            sells_by_security[trade.security_id].append(trade)

    restamped = 0
    for lot in unsourced:
        candidates = [
            t for t in sells_by_security.get(lot.security_id, [])
            if t.quantity is not None and abs(t.quantity) == lot.quantity
            and t.trade_date is not None
            and (lot.close_date is None or t.trade_date <= lot.close_date)
        ]
        if len(candidates) != 1:
            continue
        trade = candidates[0]
        logger.info(
            f"Re-stamped closed lot id={lot.id} (security_id={lot.security_id}): "
            f"close_date {lot.close_date} -> {trade.trade_date}, source heuristic -> trade"
        )
        lot.close_date = trade.trade_date
        lot.close_source = "trade"
        restamped += 1

    if restamped:
        await taxlot_repo.session.flush()
    return restamped
