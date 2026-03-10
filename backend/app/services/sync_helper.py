"""
Sync Helper
Shared tax lot reconciliation logic used by both sync.py router and scheduler_service.py.

Instead of deleting ALL tax lots on sync (losing history of sold positions),
this module:
1. Snapshots existing open lots
2. Deletes only open lots
3. Creates new lots from IBKR data
4. Detects sold positions by comparing snapshot vs incoming
5. Creates closed lot records for fully/partially sold positions
"""
import logging
from decimal import Decimal
from typing import Dict, List, Set, Tuple

from app.services.currency_service import CurrencyService
from app.repositories.taxlot_repository import TaxLotRepository

logger = logging.getLogger(__name__)


def _lot_key(security_id: int, open_date, price_per_unit: Decimal) -> Tuple:
    """Build a composite key for matching tax lots across syncs."""
    return (security_id, open_date, round(float(price_per_unit), 2))


async def reconcile_taxlots(
    taxlot_repo: TaxLotRepository,
    currency_service: CurrencyService,
    conid_to_security_id: Dict[str, int],
    taxlots_data: List[Dict],
    report_to_date,
) -> Dict:
    """
    Reconcile incoming IBKR tax lots against existing open lots.

    Preserves closed lot history and detects newly sold positions.

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

    # --- Phase A: Snapshot existing open lots ---
    snapshot: Dict[Tuple, Dict] = {}
    all_security_ids = set(conid_to_security_id.values())

    for security_id in all_security_ids:
        open_lots = await taxlot_repo.get_by_security_id(security_id, is_open=True)
        for lot in open_lots:
            key = _lot_key(lot.security_id, lot.open_date, lot.price_per_unit)
            snapshot[key] = {
                "quantity": lot.quantity,
                "cost_basis_eur": lot.cost_basis_eur,
                "cost_basis": lot.cost_basis,
                "currency": lot.currency,
                "security_id": lot.security_id,
                "open_date": lot.open_date,
                "price_per_unit": lot.price_per_unit,
            }

    logger.info(f"Snapshot: {len(snapshot)} existing open lots")

    # --- Phase B: Delete existing OPEN lots only (preserves closed lots) ---
    for security_id in all_security_ids:
        await taxlot_repo.delete_open_by_security_id(security_id)

    # --- Phase C: Create new lots from IBKR data, track incoming keys ---
    incoming_keys: Dict[Tuple, Dict] = {}

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

        key = _lot_key(security_id, lot_data["open_date"], lot_data["price_per_unit"])
        incoming_keys[key] = {
            "quantity": lot_data["quantity"],
            "cost_basis_eur": cost_basis_eur,
        }

    # --- Phase D: Reconcile — detect sold positions ---
    close_date = report_to_date

    for key, old in snapshot.items():
        if key not in incoming_keys:
            # Fully sold — create closed lot record
            if close_date:
                closed_data = {
                    "security_id": old["security_id"],
                    "open_date": old["open_date"],
                    "quantity": old["quantity"],
                    "cost_basis": old["cost_basis"],
                    "price_per_unit": old["price_per_unit"],
                    "currency": old["currency"],
                    "cost_basis_eur": old["cost_basis_eur"],
                    "is_open": False,
                    "close_date": close_date,
                }
                await taxlot_repo.create(closed_data)
                lots_closed_full += 1
                logger.info(
                    f"Closed lot: security_id={old['security_id']}, "
                    f"open_date={old['open_date']}, qty={old['quantity']}, "
                    f"close_date={close_date}"
                )
        else:
            # Key exists in both — check for partial sell
            new = incoming_keys[key]
            if new["quantity"] < old["quantity"]:
                sold_qty = old["quantity"] - new["quantity"]
                # Proportional cost_basis_eur for the sold portion
                proportion = sold_qty / old["quantity"]
                sold_cost_eur = old["cost_basis_eur"] * proportion
                sold_cost = old["cost_basis"] * proportion

                if close_date:
                    closed_data = {
                        "security_id": old["security_id"],
                        "open_date": old["open_date"],
                        "quantity": sold_qty,
                        "cost_basis": sold_cost,
                        "price_per_unit": old["price_per_unit"],
                        "currency": old["currency"],
                        "cost_basis_eur": sold_cost_eur,
                        "is_open": False,
                        "close_date": close_date,
                    }
                    await taxlot_repo.create(closed_data)
                    lots_closed_partial += 1
                    logger.info(
                        f"Partial close: security_id={old['security_id']}, "
                        f"open_date={old['open_date']}, sold_qty={sold_qty}, "
                        f"remaining_qty={new['quantity']}, close_date={close_date}"
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
