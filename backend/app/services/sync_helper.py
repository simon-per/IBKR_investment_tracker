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
from typing import Dict, List, Set

from app.services.currency_service import CurrencyService
from app.repositories.taxlot_repository import TaxLotRepository

logger = logging.getLogger(__name__)

# When the share count of a security drops between syncs, distinguish a real sale
# from a reverse split / share consolidation: a sale reduces total cost basis,
# whereas a split conserves it (fewer shares, higher price, same money). If the
# incoming cost basis is at least this fraction of the snapshot cost basis, the
# drop is treated as a corporate action, not a sale. The 1% band also absorbs
# reverse-split cash-in-lieu of fractional shares.
COST_CONSERVED_RATIO = Decimal("0.99")


async def reconcile_taxlots(
    taxlot_repo: TaxLotRepository,
    currency_service: CurrencyService,
    conid_to_security_id: Dict[str, int],
    taxlots_data: List[Dict],
    report_to_date,
) -> Dict:
    """
    Reconcile incoming IBKR tax lots against existing open lots.

    Preserves closed lot history and detects newly sold positions by comparing
    the total quantity held per security (snapshot vs incoming).

    Args:
        taxlot_repo: TaxLotRepository instance
        currency_service: CurrencyService instance
        conid_to_security_id: Map of IBKR conid -> database security_id
        taxlots_data: List of tax lot dicts from ibkr_service.extract_taxlots()
        report_to_date: The to_date from the flex report (used as close_date for sold lots)

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

    for security_id, snap_lots in snapshot.items():
        snapshot_qty = sum((lot["quantity"] for lot in snap_lots), Decimal("0"))
        sold_qty = snapshot_qty - incoming_qty.get(security_id, Decimal("0"))

        if sold_qty <= 0:
            # No net reduction: unchanged holding, a buy, forward split, or pure price drift.
            continue

        # Reverse split / share consolidation reduces the share count while conserving
        # total cost basis (fewer shares, higher price, same money); a real sale reduces
        # cost basis. If cost basis is (near) conserved despite fewer shares, refresh the
        # open lots but do NOT record a sale.
        snapshot_cost = sum((lot["cost_basis"] for lot in snap_lots), Decimal("0"))
        inc_cost = incoming_cost.get(security_id, Decimal("0"))
        if snapshot_cost > 0 and inc_cost >= snapshot_cost * COST_CONSERVED_RATIO:
            logger.info(
                f"security_id={security_id}: qty dropped {sold_qty} but cost basis "
                f"conserved ({inc_cost}/{snapshot_cost}) — split/consolidation, not a sale"
            )
            continue

        if not close_date:
            # No report date to stamp the closure with — skip creating closed lots.
            logger.warning(
                f"Sold {sold_qty} shares of security_id={security_id} but no "
                f"report_to_date available; skipping closed-lot creation"
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
                "close_date": close_date,
            }
            await taxlot_repo.create(closed_data)

            if take == lot["quantity"]:
                lots_closed_full += 1
            else:
                lots_closed_partial += 1
            logger.info(
                f"Closed lot (FIFO): security_id={lot['security_id']}, "
                f"open_date={lot['open_date']}, sold_qty={take}, "
                f"close_date={close_date}"
            )
            remaining -= take

        if remaining > 0:
            # Snapshot didn't hold enough shares to cover the reported drop.
            # This shouldn't happen; log it for visibility rather than silently drop.
            logger.warning(
                f"Reconcile: security_id={security_id} sold_qty exceeded snapshot "
                f"by {remaining}; closed lots may understate the sale"
            )

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
        "total_cost_basis_eur": total_cost_basis_eur,
    }
