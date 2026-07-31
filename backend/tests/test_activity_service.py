"""
The activity ledger: trades, dividends, cash flows and corporate actions unioned.

The behaviours worth pinning are the ones that carry meaning beyond "it returns rows":
the deposit-vs-transfer distinction the money-added figure hinges on, the pay-date
windowing that keeps the two dividend sources comparable, and the fact that paging
happens after the union rather than per table.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  register all mappers
from app.models.app_settings import AppSetting
from app.models.cash_flow import CashFlow, DEPOSIT_WITHDRAW, TRANSFER_IN
from app.models.corporate_action import CorporateAction
from app.models.dividend_payment import DividendPayment
from app.models.exchange_rate import ExchangeRate
from app.models.security import Security
from app.models.trade import Trade
from app.services.activity_service import (
    ActivityService,
    CASH_FLOW,
    CORPORATE_ACTION,
    DIVIDEND,
    MAX_LIMIT,
    TRADE,
)

TODAY = date(2026, 7, 31)
WINDOW_START = TODAY - timedelta(days=365)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()
    await engine.dispose()


async def seed(session: AsyncSession, base_currency: str = "EUR") -> None:
    session.add(AppSetting(key="base_currency", value=base_currency))

    # `trades` and `corporate_actions` store money in the trade's OWN currency — there
    # is no _eur column on either — so every non-EUR row needs a native->EUR rate before
    # the base-currency projection. A flat 0.5 makes the two steps individually visible
    # in the assertions below.
    d = WINDOW_START - timedelta(days=5)
    while d <= TODAY:
        session.add(ExchangeRate(date=d, from_currency="USD", to_currency="EUR",
                                 rate=Decimal("0.5"), source="test"))
        d += timedelta(days=1)
    session.add(Security(id=1, isin="US0378331005", symbol="AAPL", description="Apple",
                         currency="USD", conid=103, asset_category="STK", exchange="NASDAQ"))
    session.add(Security(id=2, isin="NL0010273215", symbol="ASML", description="ASML",
                         currency="EUR", conid=101, asset_category="STK", exchange="AEB"))

    session.add(Trade(
        ib_key="T-BUY", conid="103", security_id=1, symbol="AAPL",
        trade_date=TODAY - timedelta(days=100), buy_sell="BUY",
        quantity=Decimal("10"), price=Decimal("100"), proceeds=Decimal("-1000"),
        commission=Decimal("-1"), currency="USD", realized_pnl=None,
    ))
    session.add(Trade(
        ib_key="T-SELL", conid="103", security_id=1, symbol="AAPL",
        trade_date=TODAY - timedelta(days=40), buy_sell="SELL",
        quantity=Decimal("-10"), price=Decimal("120"), proceeds=Decimal("1200"),
        commission=Decimal("-1"), currency="USD", realized_pnl=Decimal("199"),
    ))
    # A fully-sold security leaves OpenPositions, so security_id can be NULL.
    session.add(Trade(
        ib_key="T-ORPHAN", conid="999", security_id=None, symbol="GONE",
        trade_date=TODAY - timedelta(days=30), buy_sell="SELL",
        quantity=Decimal("-5"), price=Decimal("10"), proceeds=Decimal("50"),
        commission=Decimal("-1"), currency="EUR", realized_pnl=Decimal("5"),
    ))

    session.add(CashFlow(
        ib_key="CF-DEP", flow_date=TODAY - timedelta(days=90),
        flow_type=DEPOSIT_WITHDRAW, amount=Decimal("2000"),
        amount_eur=Decimal("2000"), currency="EUR", description="deposit",
    ))
    session.add(CashFlow(
        ib_key="CF-WDR", flow_date=TODAY - timedelta(days=60),
        flow_type=DEPOSIT_WITHDRAW, amount=Decimal("-300"),
        amount_eur=Decimal("-300"), currency="EUR", description="withdrawal",
    ))
    # In-kind: no cash, and never money in.
    session.add(CashFlow(
        ib_key="CF-XFER", flow_date=TODAY - timedelta(days=200),
        flow_type=TRANSFER_IN, amount=Decimal("0"),
        amount_eur=Decimal("0"), currency="EUR", description="broker transfer",
    ))

    session.add(CorporateAction(
        ib_key="CA-1", conid="101", security_id=2, symbol="ASML",
        action_date=TODAY - timedelta(days=70), action_type="FORWARDSPLIT",
        quantity=Decimal("10"), value=None, proceeds=None, currency="EUR",
        description="ASML(NL0010273215) SPLIT 2 FOR 1",
    ))

    session.add(DividendPayment(
        security_id=2, ex_date=TODAY - timedelta(days=80),
        pay_date=TODAY - timedelta(days=50), shares_held=Decimal("10"),
        gross_amount_eur=Decimal("12"), withholding_tax_eur=Decimal("2"),
        net_amount_eur=Decimal("10"), currency="EUR", source="ibkr",
    ))
    # Pre-ownership zero row from yfinance's full history — must not appear.
    session.add(DividendPayment(
        security_id=2, ex_date=date(1999, 4, 4), pay_date=date(1999, 4, 4),
        shares_held=Decimal("0"), gross_amount_eur=Decimal("0"),
        withholding_tax_eur=Decimal("0"), net_amount_eur=Decimal("0"),
        currency="EUR", source="yfinance_estimate",
    ))
    await session.flush()
    await session.commit()


async def fetch(session, **kwargs):
    kwargs.setdefault("start_date", WINDOW_START)
    kwargs.setdefault("end_date", TODAY)
    return await ActivityService(session).get_activity(**kwargs)


@pytest.mark.asyncio
async def test_all_four_sources_appear_in_one_list(db):
    await seed(db)
    result = await fetch(db)

    kinds = {row["kind"] for row in result["items"]}
    assert kinds == {TRADE, DIVIDEND, CASH_FLOW, CORPORATE_ACTION}


@pytest.mark.asyncio
async def test_rows_are_newest_first(db):
    await seed(db)
    dates = [row["date"] for row in (await fetch(db))["items"]]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_a_transfer_is_shown_but_never_counts_as_money_in(db):
    """
    The audit CLAUDE.md prescribes before trusting any money-added figure, which was
    only runnable as `manage_cash_flows list` over ssh. An unexcluded transfer shows a
    portfolio-sized fake contribution, so the flag has to be on the row.
    """
    await seed(db)
    flows = {r["ib_key"]: r for r in (await fetch(db))["items"] if r["kind"] == CASH_FLOW}

    assert flows["CF-XFER"]["counts_as_money_in"] is False
    assert flows["CF-DEP"]["counts_as_money_in"] is True
    # A withdrawal is still a DEPOSITWITHDRAW row; the sign is what distinguishes it.
    assert flows["CF-WDR"]["counts_as_money_in"] is True
    assert flows["CF-WDR"]["amount_base"] == -300.0


@pytest.mark.asyncio
async def test_only_cash_flows_carry_the_money_in_flag(db):
    """None, not False: a trade is not a non-deposit, the question does not apply."""
    await seed(db)
    for row in (await fetch(db))["items"]:
        if row["kind"] != CASH_FLOW:
            assert row["counts_as_money_in"] is None


@pytest.mark.asyncio
async def test_a_trades_amount_is_its_net_cash_effect(db):
    await seed(db)
    trades = {r["ib_key"]: r for r in (await fetch(db))["items"] if r["kind"] == TRADE}

    # proceeds already carry IBKR's sign, commission is separately negative — and both
    # are USD here, so they convert at 0.5 before the (identity) EUR base projection.
    assert trades["T-BUY"]["amount_base"] == pytest.approx(-1001.0 * 0.5)
    assert trades["T-SELL"]["amount_base"] == pytest.approx(1199.0 * 0.5)
    assert trades["T-SELL"]["realized_pnl_base"] == pytest.approx(199.0 * 0.5)
    # A buy realizes nothing; that is absent, not zero.
    assert trades["T-BUY"]["realized_pnl_base"] is None
    # A EUR trade needs no conversion at all.
    assert trades["T-ORPHAN"]["amount_base"] == pytest.approx(49.0)


@pytest.mark.asyncio
async def test_a_native_currency_amount_is_converted_before_it_is_projected(db):
    """
    The bug this caught in production. `trades.proceeds` and `realized_pnl` are in the
    trade's OWN currency — unlike `cash_flows.amount_eur`, which ingest pre-converts —
    so applying only the EUR->base factor both skips native->EUR and then scales a
    number that was never EUR. A CAD 30.27 realized gain was reported as CHF 27.85 (the
    EUR->CHF factor) instead of roughly CHF 18.

    Two independent factors here, so a single-step conversion cannot pass by accident:
    USD->EUR at 0.5 and EUR->CHF at 2.0.
    """
    await seed(db, base_currency="CHF")
    d = WINDOW_START - timedelta(days=5)
    while d <= TODAY:
        db.add(ExchangeRate(date=d, from_currency="EUR", to_currency="CHF",
                            rate=Decimal("2.0"), source="test"))
        d += timedelta(days=1)
    await db.commit()

    trades = {r["ib_key"]: r for r in (await fetch(db))["items"] if r["kind"] == TRADE}

    # 1199 USD -> 599.5 EUR -> 1199 CHF. Numerically back where it started, which is
    # exactly why the factors were chosen: the buggy one-step path gives 2398.
    assert trades["T-SELL"]["amount_base"] == pytest.approx(1199.0)
    assert trades["T-SELL"]["realized_pnl_base"] == pytest.approx(199.0)
    # The EUR trade only takes the second step.
    assert trades["T-ORPHAN"]["amount_base"] == pytest.approx(49.0 * 2.0)


@pytest.mark.asyncio
async def test_an_unconvertible_amount_is_blank_rather_than_mis_scaled(db):
    """
    No rate for the pair: the row still appears with the figure absent. Dropping it
    would hide a trade from the ledger, and passing the native number through would
    report a TWD figure as CHF — the shape that once made a sale read ~35x high.
    """
    await seed(db)
    db.add(Trade(
        ib_key="T-TWD", conid="777", security_id=None, symbol="2330",
        trade_date=TODAY - timedelta(days=10), buy_sell="SELL",
        quantity=Decimal("-12"), price=Decimal("1000"), proceeds=Decimal("12000"),
        commission=Decimal("-20"), currency="TWD", realized_pnl=Decimal("500"),
    ))
    await db.commit()

    row = next(r for r in (await fetch(db))["items"] if r["ib_key"] == "T-TWD")
    assert row["amount_base"] is None
    assert row["realized_pnl_base"] is None
    # But the non-money columns still carry what is known.
    assert row["quantity"] == -12.0 and row["currency"] == "TWD"


@pytest.mark.asyncio
async def test_a_buy_realizes_nothing_and_says_so(db):
    """
    IBKR sends fifoPnlRealized=0 on every BUY. Rendering that as 0.00 asserts a realized
    result where there is none — the same rule that keeps a corporate action's price
    blank. On this account it was 67 rows of noise against 4 real ones.
    """
    await seed(db)
    trades = [r for r in (await fetch(db))["items"] if r["kind"] == TRADE]

    buys = [r for r in trades if r["subtype"] == "BUY"]
    assert buys and all(r["realized_pnl_base"] is None for r in buys)
    assert any(r["realized_pnl_base"] is not None for r in trades if r["subtype"] == "SELL")


@pytest.mark.asyncio
async def test_a_sell_with_no_surviving_security_still_appears(db):
    """security_id is NULL once a holding is fully sold — the row must not vanish."""
    await seed(db)
    keys = {r["ib_key"] for r in (await fetch(db))["items"]}
    assert "T-ORPHAN" in keys


@pytest.mark.asyncio
async def test_a_dividend_is_dated_by_when_the_cash_moved(db):
    """
    yfinance stores under the ex-date and IBKR under the pay date. A ledger is about
    when money moved, so pay_date wins — 30 days apart in the fixture, which is more
    than a monthly payer's whole cycle.
    """
    await seed(db)
    dividends = [r for r in (await fetch(db))["items"] if r["kind"] == DIVIDEND]

    assert len(dividends) == 1
    assert dividends[0]["date"] == (TODAY - timedelta(days=50)).isoformat()
    # Net, not gross: the withholding was really deducted.
    assert dividends[0]["amount_base"] == 10.0
    assert dividends[0]["source"] == "ibkr"


@pytest.mark.asyncio
async def test_zero_dividend_rows_are_excluded(db):
    """
    yfinance returns a security's whole history — 1355 of 1446 rows on this account
    were zero rows reaching back to 1985. Both dividend readers filter them; so does this.
    """
    await seed(db)
    result = await ActivityService(db).get_activity(
        start_date=date(1990, 1, 1), end_date=TODAY,
    )
    assert all(r["date"][:4] != "1999" for r in result["items"])


@pytest.mark.asyncio
async def test_a_corporate_action_asserts_no_price_it_does_not_have(db):
    await seed(db)
    action = next(r for r in (await fetch(db))["items"] if r["kind"] == CORPORATE_ACTION)

    assert action["price"] is None
    assert action["amount_base"] is None      # a split moves no cash
    assert action["quantity"] == 10.0
    assert "SPLIT 2 FOR 1" in action["description"]


@pytest.mark.asyncio
async def test_the_kind_filter_narrows_the_union(db):
    await seed(db)
    result = await fetch(db, kinds=[TRADE])
    assert {r["kind"] for r in result["items"]} == {TRADE}
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_several_kinds_can_be_combined(db):
    await seed(db)
    result = await fetch(db, kinds=[TRADE, CASH_FLOW])
    assert {r["kind"] for r in result["items"]} == {TRADE, CASH_FLOW}


@pytest.mark.asyncio
async def test_the_symbol_filter_is_exact_and_case_insensitive(db):
    await seed(db)
    assert {r["symbol"] for r in (await fetch(db, symbol="aapl"))["items"]} == {"AAPL"}
    # Not a prefix match: AAP must not return AAPL.
    assert (await fetch(db, symbol="AAP"))["total"] == 0


@pytest.mark.asyncio
async def test_the_window_excludes_what_falls_outside_it(db):
    await seed(db)
    # The transfer sits 200 days back; a 100-day window must not reach it.
    result = await fetch(db, start_date=TODAY - timedelta(days=100))
    assert "CF-XFER" not in {r["ib_key"] for r in result["items"]}

    wide = await fetch(db, start_date=TODAY - timedelta(days=300))
    assert "CF-XFER" in {r["ib_key"] for r in wide["items"]}


@pytest.mark.asyncio
async def test_paging_happens_after_the_union_not_per_table(db):
    """
    The reason limits are applied to the merged list: the four sources are separately
    ordered, so a per-table limit would silently drop every dividend in a busy trading
    month. A page of 1 must therefore be the single newest event overall.
    """
    await seed(db)
    everything = (await fetch(db))["items"]

    first = await fetch(db, limit=1)
    assert first["items"] == everything[:1]
    assert first["total"] == len(everything)

    second = await fetch(db, limit=1, offset=1)
    assert second["items"] == everything[1:2]


@pytest.mark.asyncio
async def test_paging_covers_every_row_exactly_once(db):
    await seed(db)
    total = (await fetch(db))["total"]

    seen = []
    for offset in range(0, total, 2):
        seen.extend(r["ib_key"] for r in (await fetch(db, limit=2, offset=offset))["items"])

    assert len(seen) == total
    assert len(set(seen)) == total


@pytest.mark.asyncio
async def test_an_oversized_limit_is_clamped(db):
    await seed(db)
    assert (await fetch(db, limit=99_999))["limit"] == MAX_LIMIT


@pytest.mark.asyncio
async def test_empty_tables_yield_an_empty_ledger_not_an_error(db):
    db.add(AppSetting(key="base_currency", value="EUR"))
    await db.commit()

    result = await fetch(db)
    assert result["items"] == []
    assert result["total"] == 0
    assert result["base_currency"] == "EUR"


@pytest.mark.asyncio
async def test_amounts_are_projected_into_the_base_currency(db):
    """
    Production runs CHF while the tests otherwise run EUR, and each row converts at
    **its own date** — a two-year-old trade must not be restated at today's rate.
    """
    await seed(db, base_currency="CHF")
    d = WINDOW_START - timedelta(days=5)
    while d <= TODAY:
        # A deliberately moving rate: a single factor would hide a date mix-up.
        rate = "0.90" if d < TODAY - timedelta(days=50) else "1.10"
        db.add(ExchangeRate(date=d, from_currency="EUR", to_currency="CHF",
                            rate=Decimal(rate), source="test"))
        d += timedelta(days=1)
    await db.commit()

    rows = {r["ib_key"]: r for r in (await fetch(db))["items"]}
    # The deposit sits 90 days back, in the 0.90 era. amount_eur is pre-converted at
    # ingest, so this one takes the EUR->base step only.
    assert rows["CF-DEP"]["amount_base"] == pytest.approx(2000 * 0.90)
    # The sale sits 40 days back, in the 1.10 era, and is USD — both steps.
    assert rows["T-SELL"]["amount_base"] == pytest.approx(1199 * 0.5 * 1.10)
    assert rows["T-SELL"]["realized_pnl_base"] == pytest.approx(199 * 0.5 * 1.10)
    # The 200-day-old transfer picks up the older rate, not today's.
    assert rows["CF-XFER"]["amount_base"] == pytest.approx(0)


# ── CSV ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_csv_has_a_header_and_a_row_per_item(db):
    await seed(db)
    result = await fetch(db)
    lines = ActivityService.to_csv(result).strip().split("\n")

    assert lines[0].startswith("date,kind,subtype,symbol,description")
    assert len(lines) == len(result["items"]) + 1


@pytest.mark.asyncio
async def test_csv_quotes_a_description_containing_a_comma(db):
    """
    IBKR's actionDescription contains commas routinely. Hand-rolled joining would
    corrupt exactly the rows that matter most, so this goes through csv.writer.
    """
    await seed(db)
    result = await fetch(db, kinds=[CORPORATE_ACTION])
    result["items"][0]["description"] = 'SPLIT 2 FOR 1, ex "old" shares'

    line = ActivityService.to_csv(result).strip().split("\n")[1]
    assert '"SPLIT 2 FOR 1, ex ""old"" shares"' in line


@pytest.mark.asyncio
async def test_csv_leaves_an_inapplicable_figure_blank(db):
    """Not 0.00 — a corporate action has no price, and a zero would assert one."""
    await seed(db)
    result = await fetch(db, kinds=[CORPORATE_ACTION])
    fields = ActivityService.to_csv(result).strip().split("\n")[1].split(",")

    header = ActivityService.to_csv(result).strip().split("\n")[0].split(",")
    assert fields[header.index("price")] == ""


@pytest.mark.asyncio
async def test_csv_names_the_base_currency_in_its_amount_columns(db):
    await seed(db, base_currency="CHF")
    header = ActivityService.to_csv(await fetch(db)).split("\n")[0]
    assert "amount_chf" in header


@pytest.mark.asyncio
async def test_a_fractional_share_count_is_not_rounded_away(db):
    """
    The column is Numeric(18, 6) and this account trades fractional shares constantly
    (0.3 MU, 0.1 CSU), so `str(Decimal)` pads every description to six decimals and
    rounding the quantity to whole shares renders the real trades as 0 — or, for a
    sell, as -0.
    """
    await seed(db)
    db.add(Trade(
        ib_key="T-FRAC", conid="103", security_id=1, symbol="AAPL",
        trade_date=TODAY - timedelta(days=5), buy_sell="SELL",
        quantity=Decimal("-0.100000"), price=Decimal("2742"),
        proceeds=Decimal("274.2"), commission=Decimal("-1"), currency="USD",
        realized_pnl=Decimal("27.85"),
    ))
    await db.commit()

    row = next(r for r in (await fetch(db))["items"] if r["ib_key"] == "T-FRAC")
    assert row["quantity"] == -0.1
    # The padding is gone, and the whole-share rows stay whole.
    assert row["description"] == "SELL 0.1 AAPL"
    whole = next(r for r in (await fetch(db))["items"] if r["ib_key"] == "T-BUY")
    assert whole["description"] == "BUY 10 AAPL"
