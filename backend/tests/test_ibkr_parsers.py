"""
Offline tests for the IBKR Flex section parsers (extract_trades /
extract_corporate_actions / extract_cash_transactions).

These use lightweight fake statement objects carrying the real ibflex enum
members, so the STK filter and cash-action type filter run the real code path
without needing a full, valid Flex XML document. Each parser must also tolerate
a completely absent section (Flex Query not yet updated) by returning [].
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ibflex import AssetClass
from ibflex import enums

from app.services.ibkr_service import IBKRService


def _svc():
    return IBKRService(token="t", query_id="q")


def _flex(statement):
    return {"statement": statement}


@pytest.mark.asyncio
async def test_extract_trades_filters_and_maps():
    stock_sell = SimpleNamespace(
        assetCategory=AssetClass.STOCK, conid=100, symbol="AAA",
        transactionID="TX1", tradeID="TR1", tradeDate=date(2026, 3, 2), reportDate=date(2026, 3, 3),
        buySell=enums.BuySell.SELL, quantity=Decimal("-5"), tradePrice=Decimal("20"),
        proceeds=Decimal("100"), ibCommission=Decimal("-1"), currency="USD",
        fifoPnlRealized=Decimal("30"),
    )
    option_trade = SimpleNamespace(
        assetCategory=AssetClass.OPTION, conid=999, symbol="OPT",
        transactionID="TX2", tradeID="TR2", tradeDate=date(2026, 3, 2), reportDate=None,
        buySell=enums.BuySell.BUY, quantity=Decimal("1"), tradePrice=Decimal("1"),
        proceeds=Decimal("-1"), ibCommission=Decimal("0"), currency="USD",
        fifoPnlRealized=None,
    )
    statement = SimpleNamespace(Trades=[stock_sell, option_trade])

    trades = await _svc().extract_trades(_flex(statement))

    assert len(trades) == 1  # option filtered out
    t = trades[0]
    assert t["ib_key"] == "TX1"  # transactionID preferred over tradeID
    assert t["conid"] == "100"
    assert t["buy_sell"] == "SELL"
    assert t["quantity"] == Decimal("-5")  # kept signed
    assert t["realized_pnl"] == Decimal("30")
    assert t["trade_date"] == date(2026, 3, 2)
    assert t["asset_category"] == "STK"


@pytest.mark.asyncio
async def test_extract_trades_absent_section_returns_empty():
    assert await _svc().extract_trades(_flex(SimpleNamespace())) == []
    assert await _svc().extract_trades(_flex(SimpleNamespace(Trades=None))) == []


@pytest.mark.asyncio
async def test_extract_corporate_actions_maps_reverse_split():
    rs = SimpleNamespace(
        assetCategory=AssetClass.STOCK, conid=100, symbol="AAA",
        transactionID="CA1", dateTime=datetime(2026, 4, 1, 10, 0), reportDate=date(2026, 4, 1),
        type=enums.Reorg.REVERSESPLIT, quantity=Decimal("-90"), value=Decimal("0"),
        proceeds=Decimal("0"), currency="USD", actionDescription="AAA(US) SPLIT 1 FOR 10",
    )
    statement = SimpleNamespace(CorporateActions=[rs])

    actions = await _svc().extract_corporate_actions(_flex(statement))

    assert len(actions) == 1
    a = actions[0]
    assert a["ib_key"] == "CA1"
    assert a["conid"] == "100"
    assert a["action_type"] == "REVERSESPLIT"
    assert a["action_date"] == date(2026, 4, 1)
    assert a["quantity"] == Decimal("-90")


@pytest.mark.asyncio
async def test_extract_corporate_actions_absent_section_returns_empty():
    assert await _svc().extract_corporate_actions(_flex(SimpleNamespace())) == []


@pytest.mark.asyncio
async def test_extract_cash_transactions_keeps_only_dividend_types():
    dividend = SimpleNamespace(
        type=enums.CashAction.DIVIDEND, conid=100, symbol="AAA",
        transactionID="C1", settleDate=date(2026, 5, 2), dateTime=datetime(2026, 5, 1, 0, 0),
        reportDate=date(2026, 5, 1), amount=Decimal("42.50"), currency="USD",
        description="AAA CASH DIVIDEND",
    )
    withholding = SimpleNamespace(
        type=enums.CashAction.WHTAX, conid=100, symbol="AAA",
        transactionID="C2", settleDate=date(2026, 5, 2), dateTime=datetime(2026, 5, 1, 0, 0),
        reportDate=date(2026, 5, 1), amount=Decimal("-6.38"), currency="USD",
        description="AAA WITHHOLDING @ 15%",
    )
    deposit = SimpleNamespace(
        type=enums.CashAction.DEPOSITWITHDRAW, conid=None, symbol=None,
        transactionID="C3", settleDate=date(2026, 5, 2), dateTime=datetime(2026, 5, 1, 0, 0),
        reportDate=date(2026, 5, 1), amount=Decimal("1000"), currency="USD", description="ACH",
    )
    statement = SimpleNamespace(CashTransactions=[dividend, withholding, deposit])

    txns = await _svc().extract_cash_transactions(_flex(statement))

    assert len(txns) == 2  # deposit filtered out
    by_type = {t["type"]: t for t in txns}
    assert by_type["DIVIDEND"]["amount"] == Decimal("42.50")
    assert by_type["WHTAX"]["amount"] == Decimal("-6.38")  # kept signed (negative)
    assert by_type["DIVIDEND"]["pay_date"] == date(2026, 5, 2)  # settleDate preferred


@pytest.mark.asyncio
async def test_extract_cash_transactions_absent_section_returns_empty():
    assert await _svc().extract_cash_transactions(_flex(SimpleNamespace())) == []


# ── extract_taxlots: openDateTime comes off the parsed row ──────────────
#
# It used to be scraped from the raw XML into a separate list and matched back by
# position index. That list kept only STK rows carrying the attribute while the
# loop enumerated *every* OpenPosition, so one non-STK row — or one lot without
# the attribute — shifted every index after it. The conid check turned the
# mismatch into a silent fallback to reportDate rather than realigning, stamping
# every later lot with the statement date. ibflex 0.15 parses the field itself:
#   parse_element_attr(Types.OpenPosition, 'openDateTime', '20251013;112102')
#     -> datetime(2025, 10, 13, 11, 21, 2)

_OPEN_POSITIONS_XML = """<FlexQueryResponse queryName="Portfolio" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1" fromDate="2026-01-01" toDate="2026-07-24"
 period="YearToDate" whenGenerated="2026-07-24;120000">
 <OpenPositions>
  <OpenPosition assetCategory="STK" symbol="AAA" conid="1001" isin="US0000000001"
   description="A CORP" currency="EUR" listingExchange="NASDAQ" position="10"
   costBasisPrice="100" costBasisMoney="1000" openDateTime="20240115;093000"
   levelOfDetail="LOT" reportDate="2026-07-24" />
  <OpenPosition assetCategory="BOND" symbol="BND" conid="2002"
   description="A BOND" currency="EUR" position="5"
   costBasisPrice="98" costBasisMoney="490" openDateTime="20250601;093000"
   levelOfDetail="LOT" reportDate="2026-07-24" />
  <OpenPosition assetCategory="STK" symbol="CCC" conid="3003" isin="US0000000003"
   description="C CORP" currency="EUR" listingExchange="NASDAQ" position="7"
   costBasisPrice="50" costBasisMoney="350" openDateTime="20260302;140000"
   levelOfDetail="LOT" reportDate="2026-07-24" />
 </OpenPositions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""


@pytest.mark.asyncio
async def test_a_non_stk_row_does_not_shift_later_lots_open_dates():
    svc = _svc()
    flex_data = svc.parse_flex_xml(_OPEN_POSITIONS_XML.encode())

    taxlots = await svc.extract_taxlots(flex_data)

    by_conid = {t["conid"]: t for t in taxlots}
    assert set(by_conid) == {"1001", "3003"}          # the bond is filtered out
    assert by_conid["1001"]["open_date"] == date(2024, 1, 15)
    # The row after the bond is the one the index shift used to break: it read
    # reportDate (2026-07-24), the day the sync noticed it, not the purchase.
    assert by_conid["3003"]["open_date"] == date(2026, 3, 2)


@pytest.mark.asyncio
async def test_a_lot_without_an_open_date_falls_back_to_report_date():
    xml = _OPEN_POSITIONS_XML.replace(' openDateTime="20260302;140000"', "")
    svc = _svc()

    taxlots = await svc.extract_taxlots(svc.parse_flex_xml(xml.encode()))

    by_conid = {t["conid"]: t for t in taxlots}
    assert by_conid["3003"]["open_date"] == date(2026, 7, 24)   # reportDate
    assert by_conid["1001"]["open_date"] == date(2024, 1, 15)   # unaffected


@pytest.mark.asyncio
async def test_open_date_time_is_narrowed_to_a_date():
    """The attribute parses to a datetime; taxlots.open_date is a Date column."""
    svc = _svc()
    flex_data = svc.parse_flex_xml(_OPEN_POSITIONS_XML.encode())

    for lot in await svc.extract_taxlots(flex_data):
        assert type(lot["open_date"]) is date
