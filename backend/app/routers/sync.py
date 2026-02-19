"""
Sync Router
Handles syncing data from IBKR Flex Query to local database.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict
from decimal import Decimal

from app.database import get_db
from app.services.ibkr_service import IBKRService
from app.services.currency_service import CurrencyService
from app.repositories.security_repository import SecurityRepository
from app.repositories.taxlot_repository import TaxLotRepository


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

        # Step 4: Extract tax lots
        taxlots_data = await ibkr_service.extract_taxlots(flex_data)

        # Step 5: Process and store tax lots
        taxlots_count = 0
        taxlots_skipped = 0
        skipped_currencies = set()
        total_cost_basis_eur = Decimal('0')

        # Delete all existing taxlots before syncing fresh data from IBKR
        # This ensures we always have the latest data from IBKR
        print("Deleting existing taxlots before sync...")
        for conid, security_id in conid_to_security_id.items():
            await taxlot_repo.delete_by_security_id(security_id)

        for lot_data in taxlots_data:
            conid = lot_data['conid']

            # Get the security ID from our database
            security_id = conid_to_security_id.get(conid)
            if not security_id:
                # Security not found, skip this taxlot
                print(f"Warning: Security with conid {conid} not found, skipping taxlot")
                taxlots_skipped += 1
                continue

            # Convert cost basis to EUR
            try:
                cost_basis_eur = await currency_service.convert_to_eur(
                    amount=lot_data['cost_basis'],
                    from_currency=lot_data['currency'],
                    target_date=lot_data['open_date']
                )
            except ValueError as e:
                # Currency not supported by Frankfurter API (e.g., RUB, CNY, etc.)
                print(f"Warning: Skipping taxlot with unsupported currency {lot_data['currency']}: {str(e)}")
                skipped_currencies.add(lot_data['currency'])
                taxlots_skipped += 1
                continue

            # Create new taxlot
            taxlot_data = {
                'security_id': security_id,
                'open_date': lot_data['open_date'],
                'quantity': lot_data['quantity'],
                'cost_basis': lot_data['cost_basis'],
                'price_per_unit': lot_data['price_per_unit'],
                'currency': lot_data['currency'],
                'cost_basis_eur': cost_basis_eur,
                'is_open': lot_data['is_open'],
            }

            await taxlot_repo.create(taxlot_data)
            taxlots_count += 1
            total_cost_basis_eur += cost_basis_eur

        # Commit transaction
        await db.commit()

        result = {
            "status": "success",
            "message": "Successfully synced data from IBKR",
            "securities_synced": securities_count,
            "taxlots_synced": taxlots_count,
            "taxlots_skipped": taxlots_skipped,
            "total_cost_basis_eur": float(total_cost_basis_eur),
            "account_id": flex_data['account_id'],
            "data_from": str(flex_data['from_date']) if flex_data['from_date'] else None,
            "data_to": str(flex_data['to_date']) if flex_data['to_date'] else None,
        }

        # Add warning about skipped currencies if any
        if skipped_currencies:
            result["warnings"] = [
                f"Skipped {taxlots_skipped} taxlot(s) with unsupported currencies: {', '.join(sorted(skipped_currencies))}"
            ]

        return result

    except Exception as e:
        await db.rollback()
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
