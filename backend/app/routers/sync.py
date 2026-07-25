"""
Sync Router
Handles syncing data from IBKR Flex Query to local database.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, List
from datetime import datetime
from decimal import Decimal

from app.database import get_db
from app.services.ibkr_service import IBKRService
from app.services.currency_service import CurrencyService
from app.services.sync_helper import reconcile_taxlots, persist_transactions
from app.services.benchmark_service import BenchmarkService
from app.services.dividend_service import DividendService
from app.repositories.security_repository import SecurityRepository
from app.repositories.taxlot_repository import TaxLotRepository
from app.repositories.trade_repository import TradeRepository
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.app_settings_repository import AppSettingsRepository
from app.repositories.sync_run_repository import SyncRunRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ibkr", response_model=Dict)
async def sync_ibkr_data(db: AsyncSession = Depends(get_db)):
    """
    Sync securities and tax lots from IBKR Flex Query.

    This endpoint:
    1. Fetches data from IBKR Flex Query API
    2. Extracts securities (stocks only - no dividends, cash, etc.)
    3. Extracts tax lots (purchase history)
    4. Converts cost basis to EUR
    5. Stores everything in the database

    Returns:
        Summary of synced data including counts
    """
    started_at = datetime.now()
    try:
        # Initialize services and repositories
        ibkr_service = IBKRService()
        currency_service = CurrencyService(db)
        security_repo = SecurityRepository(db)
        taxlot_repo = TaxLotRepository(db)

        # Step 1: Fetch data from IBKR
        flex_data = await ibkr_service.fetch_flex_data()

        # Step 2: Extract securities
        securities_data = await ibkr_service.extract_securities(flex_data)

        # Step 3: Upsert securities to database
        securities_count = 0
        conid_to_security_id = {}  # Map IBKR conid to our database ID

        for sec_data in securities_data:
            security = await security_repo.upsert(sec_data)
            conid_to_security_id[sec_data['conid']] = security.id
            securities_count += 1

        # Step 4: Persist authoritative transaction history (Trades + CorporateActions).
        # Tolerant: returns [] if those Flex sections aren't enabled yet. Additive —
        # does not affect reconciliation on its own.
        trade_repo = TradeRepository(db)
        corp_action_repo = CorporateActionRepository(db)
        app_settings = AppSettingsRepository(db)
        trades_data = await ibkr_service.extract_trades(flex_data)
        corp_actions_data = await ibkr_service.extract_corporate_actions(flex_data)
        await persist_transactions(
            trade_repo, corp_action_repo, conid_to_security_id,
            trades_data, corp_actions_data,
        )

        # Record authoritative dividend income (gross/withholding/net) from
        # <CashTransactions>. Flex-only (no Yahoo); tolerant of an absent section.
        cash_txns = await ibkr_service.extract_cash_transactions(flex_data)
        await DividendService(db).sync_dividends_from_cash_transactions(
            cash_txns, conid_to_security_id
        )

        last_sync_date = await app_settings.get_last_sync_to_date()

        # Step 5: Extract tax lots
        taxlots_data = await ibkr_service.extract_taxlots(flex_data)

        # Step 6: Reconcile tax lots (preserves closed lot history)
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

        taxlots_count = recon["taxlots_synced"]
        taxlots_skipped = recon["taxlots_skipped"]
        skipped_currencies = recon["skipped_currencies"]
        total_cost_basis_eur = recon["total_cost_basis_eur"]

        # Invalidate benchmark timeline cache (tax lots changed)
        bench_service = BenchmarkService(db)
        cleared = await bench_service.clear_cache()
        logger.info(f"Cleared {cleared} benchmark timeline cache entries (tax lots changed)")

        # Commit transaction
        await db.commit()

        result = {
            "status": "success",
            "message": "Successfully synced data from IBKR",
            "securities_synced": securities_count,
            "taxlots_synced": taxlots_count,
            "taxlots_skipped": taxlots_skipped,
            "lots_closed_full": recon["lots_closed_full"],
            "lots_closed_partial": recon["lots_closed_partial"],
            "total_cost_basis_eur": float(total_cost_basis_eur),
            "account_id": flex_data['account_id'],
            "data_from": str(flex_data['from_date']) if flex_data['from_date'] else None,
            "data_to": str(flex_data['to_date']) if flex_data['to_date'] else None,
        }

        # Surface skipped currencies plus any Flex XML schema drift the sanitizer had
        # to work around, so it's visible in the API/UI and not only in container logs.
        warnings: List[str] = []
        if skipped_currencies:
            warnings.append(
                f"Skipped {taxlots_skipped} taxlot(s) with unsupported currencies: {', '.join(sorted(skipped_currencies))}"
            )
        warnings.extend(flex_data.get('flex_warnings') or [])
        if warnings:
            result["warnings"] = warnings

        # Persist the attempt so it survives container restarts (auto-deploy restarts on
        # every push). Best-effort: never turn a good sync into a failure.
        await SyncRunRepository(db).record(
            sync_type="ibkr", status="success", message=result["message"],
            details={k: v for k, v in result.items() if k not in ("message", "warnings")},
            warnings=warnings or None, started_at=started_at,
        )

        return result

    except Exception as e:
        await db.rollback()
        await SyncRunRepository(db).record(
            sync_type="ibkr", status="error", message=str(e), started_at=started_at,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync IBKR data: {str(e)}"
        )


@router.get("/status")
async def get_sync_status(db: AsyncSession = Depends(get_db)):
    """
    Get current sync status - count of securities and taxlots in database.
    """
    security_repo = SecurityRepository(db)
    taxlot_repo = TaxLotRepository(db)

    securities = await security_repo.get_all(limit=1000)
    open_taxlots = await taxlot_repo.get_open_taxlots()

    total_cost_basis_eur = sum(
        lot.cost_basis_eur for lot in open_taxlots
    )

    return {
        "securities_count": len(securities),
        "open_taxlots_count": len(open_taxlots),
        "total_cost_basis_eur": float(total_cost_basis_eur),
    }
