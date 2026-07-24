"""
Regression tests for reconcile_taxlots (backend/app/services/sync_helper.py).

Focus: a per-share cost-basis change (e.g. the S&P Global -> Mobility Global
spinoff, which makes IBKR re-allocate costBasisPrice for days) must NOT be
mistaken for a sale. Reconciliation is by quantity held per security, so price
drift creates no phantom closed lots. Genuine quantity reductions still close
lots FIFO.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  register all mappers for relationship config
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.repositories.taxlot_repository import TaxLotRepository
from app.services.sync_helper import reconcile_taxlots


class FakeCurrencyService:
    """Identity EUR conversion so cost_basis == cost_basis_eur in tests."""

    async def convert_to_eur(self, amount, from_currency, target_date):
        return Decimal(str(amount))


async def _make_repo():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    # Create only the tables this test needs. Full-metadata create_all trips a
    # pre-existing duplicate index in an unrelated model (analyst_ratings);
    # production is unaffected because it uses migrations / pre-existing tables.
    tables = [Security.__table__, TaxLot.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session = AsyncSession(engine, expire_on_commit=False)
    return engine, session, TaxLotRepository(session)


async def _seed_open_lot(repo, security_id, open_date, quantity, price, currency="USD"):
    q = Decimal(str(quantity))
    p = Decimal(str(price))
    cost = q * p
    await repo.create({
        "security_id": security_id,
        "open_date": open_date,
        "quantity": q,
        "cost_basis": cost,
        "price_per_unit": p,
        "currency": currency,
        "cost_basis_eur": cost,  # identity conversion
        "is_open": True,
    })


def _incoming(conid, open_date, quantity, price, currency="USD"):
    q = Decimal(str(quantity))
    p = Decimal(str(price))
    return {
        "conid": conid,
        "open_date": open_date,
        "quantity": q,
        "cost_basis": q * p,
        "price_per_unit": p,
        "currency": currency,
        "is_open": True,
    }


@pytest.mark.asyncio
async def test_price_drift_same_quantity_creates_no_closed_lots():
    """The core bug: daily cost-basis drift after a spinoff must not close lots."""
    engine, session, repo = await _make_repo()
    try:
        # Existing open lot: 3 shares @ 492.47
        await _seed_open_lot(repo, security_id=1, open_date=date(2025, 11, 6),
                             quantity=3, price=492.47)

        # Incoming: same 3 shares but price drifted to 468.55 (spinoff reallocation)
        incoming = [_incoming("100", date(2025, 11, 6), 3, 468.55)]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 3),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 0
        # Exactly one open lot remains (the re-synced one), no closed lots at all.
        assert len(await repo.get_by_security_id(1, is_open=True)) == 1
        assert len(await repo.get_by_security_id(1, is_open=False)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_full_sale_closes_all_shares():
    """Security absent from incoming -> whole position closed."""
    engine, session, repo = await _make_repo()
    try:
        await _seed_open_lot(repo, security_id=1, open_date=date(2025, 11, 6),
                             quantity=3, price=236.38)

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={},   # security no longer reported by IBKR
            taxlots_data=[],
            report_to_date=date(2026, 4, 17),
        )

        assert result["lots_closed_full"] == 1
        assert result["lots_closed_partial"] == 0
        closed = await repo.get_by_security_id(1, is_open=False)
        assert len(closed) == 1
        assert closed[0].quantity == Decimal("3")
        assert closed[0].close_date == date(2026, 4, 17)
        assert len(await repo.get_by_security_id(1, is_open=True)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_partial_sale_closes_sold_qty_fifo():
    """Selling 1 of 5 shares closes 1 share from the OLDEST lot (FIFO)."""
    engine, session, repo = await _make_repo()
    try:
        # Two lots: older 3 @ 492.47, newer 2 @ 530.31  (total 5)
        await _seed_open_lot(repo, 1, date(2025, 11, 6), 3, 492.47)
        await _seed_open_lot(repo, 1, date(2025, 12, 29), 2, 530.31)

        # Incoming total = 4 (sold 1). Lot composition is irrelevant; only total qty matters.
        incoming = [
            _incoming("100", date(2025, 11, 6), 2, 492.47),
            _incoming("100", date(2025, 12, 29), 2, 530.31),
        ]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 6, 22),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 1
        closed = await repo.get_by_security_id(1, is_open=False)
        assert len(closed) == 1
        assert closed[0].quantity == Decimal("1")
        assert closed[0].open_date == date(2025, 11, 6)  # oldest lot consumed first
        # Proportional cost basis: 1/3 of the older lot's 1477.41 == 492.47
        assert float(closed[0].cost_basis_eur) == pytest.approx(492.47, abs=0.01)
        # 4 shares remain open
        open_lots = await repo.get_by_security_id(1, is_open=True)
        assert sum(l.quantity for l in open_lots) == Decimal("4")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_multiple_same_day_lots_preserved_on_drift():
    """Several distinct lots sharing (security, open_date) are not collapsed or closed."""
    engine, session, repo = await _make_repo()
    try:
        # 3 separate 1-share lots bought the same day at different prices
        await _seed_open_lot(repo, 1, date(2025, 6, 17), 1, 100.00)
        await _seed_open_lot(repo, 1, date(2025, 6, 17), 1, 101.00)
        await _seed_open_lot(repo, 1, date(2025, 6, 17), 1, 102.00)

        # Incoming: same 3 shares, prices drifted
        incoming = [
            _incoming("100", date(2025, 6, 17), 1, 99.50),
            _incoming("100", date(2025, 6, 17), 1, 100.50),
            _incoming("100", date(2025, 6, 17), 1, 101.50),
        ]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 8),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 0
        assert len(await repo.get_by_security_id(1, is_open=True)) == 3
        assert len(await repo.get_by_security_id(1, is_open=False)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_forward_split_creates_no_closed_lots():
    """Forward split (share count increases, cost basis conserved) is not a sale."""
    engine, session, repo = await _make_repo()
    try:
        await _seed_open_lot(repo, 1, date(2025, 11, 6), 100, 5.00)  # cost 500
        # 2:1 split: 200 shares @ 2.50, same total cost
        incoming = [_incoming("100", date(2025, 11, 6), 200, 2.50)]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 8),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 0
        open_lots = await repo.get_by_security_id(1, is_open=True)
        assert sum(l.quantity for l in open_lots) == Decimal("200")
        assert len(await repo.get_by_security_id(1, is_open=False)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reverse_split_creates_no_closed_lots():
    """Reverse split (share count drops, cost basis conserved) must NOT record a sale."""
    engine, session, repo = await _make_repo()
    try:
        await _seed_open_lot(repo, 1, date(2025, 11, 6), 100, 5.00)  # cost 500
        # 1:10 reverse split: 10 shares @ 50, same total cost
        incoming = [_incoming("100", date(2025, 11, 6), 10, 50.00)]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 8),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 0
        open_lots = await repo.get_by_security_id(1, is_open=True)
        assert sum(l.quantity for l in open_lots) == Decimal("10")
        assert len(await repo.get_by_security_id(1, is_open=False)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reverse_split_with_cash_in_lieu_no_closure():
    """Reverse split with sub-1% cash-in-lieu of fractional shares is still a split, not a sale."""
    engine, session, repo = await _make_repo()
    try:
        await _seed_open_lot(repo, 1, date(2025, 11, 6), 105, 5.00)  # cost 525
        # 1:10 reverse split of 105 -> 10 shares; ~0.5 share paid as cash-in-lieu
        # remaining cost 522 (~99.4% of 525, within the 1% conservation band)
        incoming = [_incoming("100", date(2025, 11, 6), 10, 52.20)]  # cost 522

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 8),
        )

        assert result["lots_closed_full"] == 0
        assert result["lots_closed_partial"] == 0
        assert len(await repo.get_by_security_id(1, is_open=False)) == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_genuine_sale_still_closes_when_cost_drops():
    """A real partial sale (share count AND cost basis drop together) still closes a lot."""
    engine, session, repo = await _make_repo()
    try:
        await _seed_open_lot(repo, 1, date(2025, 11, 6), 100, 5.00)  # cost 500
        # Sold 40 shares at the same price: 60 @ 5 remain (cost 300, dropped 40%)
        incoming = [_incoming("100", date(2025, 11, 6), 60, 5.00)]

        result = await reconcile_taxlots(
            repo, FakeCurrencyService(),
            conid_to_security_id={"100": 1},
            taxlots_data=incoming,
            report_to_date=date(2026, 7, 8),
        )

        assert result["lots_closed_full"] + result["lots_closed_partial"] == 1
        closed = await repo.get_by_security_id(1, is_open=False)
        assert len(closed) == 1
        assert closed[0].quantity == Decimal("40")
        open_lots = await repo.get_by_security_id(1, is_open=True)
        assert sum(l.quantity for l in open_lots) == Decimal("60")
    finally:
        await session.close()
        await engine.dispose()
