"""
Offline tests for IBKRService._sanitize_flex_xml.

The pinned ibflex maps every XML attribute onto a frozen dataclass field and
aborts the *whole* document on the first unknown one, so an attribute IBKR added
after ibflex 0.15 was released (e.g. `subCategory` on <Trade>) breaks the entire
sync. These tests drive the real ibflex parser over small but real-shaped Flex
documents — no network, no IBKR credentials.
"""
from datetime import date
from decimal import Decimal

import pytest

from ibflex import enums, parser
from ibflex.parser import FlexParserError

from app.services.ibkr_service import IBKRService


def _svc():
    return IBKRService(token="t", query_id="q")


def _wrap(body: str) -> bytes:
    """Wrap section XML in the FlexQueryResponse/FlexStatement envelope ibflex needs."""
    return (
        '<FlexQueryResponse queryName="Portfolio" type="AF">'
        '<FlexStatements count="1">'
        '<FlexStatement accountId="U1234567" fromDate="2026-01-01" toDate="2026-07-01"'
        ' period="YearToDate" whenGenerated="2026-07-01;120000">'
        f'{body}'
        '</FlexStatement>'
        '</FlexStatements>'
        '</FlexQueryResponse>'
    ).encode()


def _trade(**overrides) -> str:
    """A realistic <Trade>, including the `subCategory` that breaks ibflex 0.15.

    Pass an attribute as None to omit it entirely.
    """
    attrs = {
        'assetCategory': 'STK',
        'subCategory': 'COMMON',  # added by IBKR after ibflex 0.15 — the bug
        'conid': '100',
        'symbol': 'AAA',
        'transactionID': 'TX1',
        'tradeID': 'TR1',
        'tradeDate': '2026-03-02',
        'reportDate': '2026-03-03',
        'buySell': 'SELL',
        'quantity': '-5',
        'tradePrice': '20',
        'proceeds': '100',
        'ibCommission': '-1',
        'currency': 'USD',
        'fifoPnlRealized': '30',
        'levelOfDetail': 'EXECUTION',
    }
    attrs.update(overrides)
    rendered = ' '.join(f'{k}="{v}"' for k, v in attrs.items() if v is not None)
    return f'<Trade {rendered} />'


_TRADES = _wrap(f'<Trades>{_trade()}</Trades>')

_CASH_TRANSACTIONS = _wrap(
    '<CashTransactions>'
    '<CashTransaction type="Dividends" assetCategory="STK" subCategory="COMMON" conid="100"'
    ' symbol="AAA" transactionID="C1" dateTime="2026-05-01" settleDate="2026-05-02"'
    ' levelOfDetail="DETAIL" amount="42.50" currency="USD" description="AAA DIVIDEND" />'
    '<CashTransaction type="Withholding Tax" assetCategory="STK" subCategory="COMMON" conid="100"'
    ' symbol="AAA" transactionID="C2" dateTime="2026-05-01" settleDate="2026-05-02"'
    ' levelOfDetail="DETAIL" amount="-6.38" currency="USD" description="AAA WHTAX" />'
    '</CashTransactions>'
)

_CORPORATE_ACTIONS = _wrap(
    '<CorporateActions>'
    '<CorporateAction type="RS" assetCategory="STK" subCategory="COMMON" conid="100"'
    ' symbol="AAA" transactionID="CA1" dateTime="2026-04-01" reportDate="2026-04-01"'
    ' quantity="-90" value="0" proceeds="0" currency="USD"'
    ' actionDescription="AAA(US) SPLIT 1 FOR 10" levelOfDetail="DETAIL" />'
    '</CorporateActions>'
)


def _statement(xml: bytes):
    return parser.parse(xml).FlexStatements[0]


# --------------------------------------------------------------------------
# The bug: unknown attributes abort the whole document
# --------------------------------------------------------------------------

def test_unsanitized_trade_subcategory_breaks_ibflex():
    """Guards the premise: without sanitizing, this is the live production failure."""
    with pytest.raises(FlexParserError, match="Trade has no attribute"):
        parser.parse(_TRADES)


def test_sanitized_trade_parses_and_reports_dropped_attribute():
    sanitized, warnings = _svc()._sanitize_flex_xml(_TRADES)

    statement = _statement(sanitized)  # must not raise
    assert len(statement.Trades) == 1
    assert any('Trade.subCategory' in w for w in warnings)


@pytest.mark.parametrize('raw', [_CASH_TRANSACTIONS, _CORPORATE_ACTIONS])
def test_other_sections_also_recovered(raw):
    """`subCategory` is declared on SecurityInfo only, so <CashTransaction> and
    <CorporateAction> are the next sections that would abort the sync."""
    with pytest.raises(FlexParserError, match='has no attribute'):
        parser.parse(raw)

    sanitized, _ = _svc()._sanitize_flex_xml(raw)
    _statement(sanitized)  # must not raise


def test_surviving_trade_fields_are_intact():
    sanitized, _ = _svc()._sanitize_flex_xml(_TRADES)

    trade = _statement(sanitized).Trades[0]
    assert trade.tradeID == 'TR1'
    assert trade.transactionID == 'TX1'
    assert trade.quantity == Decimal('-5')
    assert trade.fifoPnlRealized == Decimal('30')
    assert trade.proceeds == Decimal('100')
    assert trade.currency == 'USD'


@pytest.mark.asyncio
async def test_sanitize_then_extract_trades_end_to_end():
    """The full production path: sanitize -> ibflex -> our extractor."""
    svc = _svc()
    sanitized, _ = svc._sanitize_flex_xml(_TRADES)

    trades = await svc.extract_trades({'statement': _statement(sanitized)})

    assert len(trades) == 1
    assert trades[0]['ib_key'] == 'TX1'
    assert trades[0]['buy_sell'] == 'SELL'
    assert trades[0]['realized_pnl'] == Decimal('30')


# --------------------------------------------------------------------------
# The strip is per-class, not a blanket removal
# --------------------------------------------------------------------------

def test_securityinfo_keeps_its_legitimate_subcategory():
    """`subCategory` IS declared on SecurityInfo, so it must survive there."""
    raw = _wrap(
        '<SecuritiesInfo>'
        '<SecurityInfo assetCategory="STK" subCategory="ETF" symbol="AAA" conid="100"'
        ' isin="US0000000001" description="AAA ETF" currency="USD" listingExchange="NASDAQ" />'
        '</SecuritiesInfo>'
    )

    sanitized, warnings = _svc()._sanitize_flex_xml(raw)

    assert sanitized is raw  # nothing unknown -> untouched
    assert warnings == []
    assert _statement(raw).SecuritiesInfo[0].subCategory == 'ETF'


def test_clean_xml_is_returned_unchanged():
    """No-op guarantee: a query without new attributes behaves byte-identically."""
    raw = _wrap(f'<Trades>{_trade(subCategory=None)}</Trades>')

    sanitized, warnings = _svc()._sanitize_flex_xml(raw)

    assert sanitized is raw
    assert warnings == []


# --------------------------------------------------------------------------
# Unknown enum *values* (not just unknown attribute names)
# --------------------------------------------------------------------------

_UNKNOWN_CASH_TYPE = _wrap(
    '<CashTransactions>'
    # "Broker Fees" is selectable in the Flex Query but absent from ibflex's
    # CashAction enum, so it aborts the whole document unless neutralised.
    '<CashTransaction type="Broker Fees" assetCategory="STK" conid="100" symbol="AAA"'
    ' transactionID="C0" dateTime="2026-04-01" settleDate="2026-04-01"'
    ' amount="-2.50" currency="USD" description="BROKER FEE" />'
    '<CashTransaction type="Dividends" assetCategory="STK" conid="100" symbol="AAA"'
    ' transactionID="C1" dateTime="2026-05-01" settleDate="2026-05-02"'
    ' amount="42.50" currency="USD" description="AAA DIVIDEND" />'
    '<CashTransaction type="Withholding Tax" assetCategory="STK" conid="100" symbol="AAA"'
    ' transactionID="C2" dateTime="2026-05-01" settleDate="2026-05-02"'
    ' amount="-6.38" currency="USD" description="AAA WHTAX" />'
    '</CashTransactions>'
)


def test_unknown_cash_action_value_would_abort_the_document():
    with pytest.raises(FlexParserError, match='not a valid CashAction'):
        parser.parse(_UNKNOWN_CASH_TYPE)


@pytest.mark.asyncio
async def test_unknown_cash_action_is_neutralised_not_fatal():
    """
    The unparseable row loses its `type` and is then skipped by the extractor,
    while the real dividend + withholding pair beside it still comes through.
    """
    svc = _svc()
    sanitized, warnings = svc._sanitize_flex_xml(_UNKNOWN_CASH_TYPE)

    statement = _statement(sanitized)  # must not raise
    types = [ct.type for ct in statement.CashTransactions]
    assert types.count(None) == 1  # the "Broker Fees" row was neutralised
    assert any('CashTransaction.type' in w and 'CashAction' in w for w in warnings)

    txns = await svc.extract_cash_transactions({'statement': statement})

    by_type = {t['type']: t for t in txns}
    assert set(by_type) == {'DIVIDEND', 'WHTAX'}  # fee row dropped, not counted
    assert by_type['DIVIDEND']['amount'] == Decimal('42.50')
    assert by_type['WHTAX']['amount'] == Decimal('-6.38')


@pytest.mark.asyncio
async def test_unknown_reorg_type_keeps_the_action_with_unknown_label():
    raw = _wrap(
        '<CorporateActions>'
        '<CorporateAction type="ZZ" assetCategory="STK" conid="100" symbol="AAA"'
        ' transactionID="CA9" dateTime="2026-04-01" reportDate="2026-04-01"'
        ' quantity="-90" value="0" proceeds="0" currency="USD"'
        ' actionDescription="MYSTERY REORG" />'
        '</CorporateActions>'
    )
    svc = _svc()
    sanitized, _ = svc._sanitize_flex_xml(raw)

    actions = await svc.extract_corporate_actions({'statement': _statement(sanitized)})

    assert len(actions) == 1
    assert actions[0]['action_type'] == 'UNKNOWN'
    assert actions[0]['quantity'] == Decimal('-90')  # the useful data survives
    assert actions[0]['action_date'] == date(2026, 4, 1)


@pytest.mark.asyncio
async def test_unknown_note_code_does_not_lose_the_trade():
    raw = _wrap(f'<Trades>{_trade(notes="XYZ")}</Trades>')
    svc = _svc()
    sanitized, _ = svc._sanitize_flex_xml(raw)

    trades = await svc.extract_trades({'statement': _statement(sanitized)})

    assert len(trades) == 1
    assert trades[0]['ib_key'] == 'TX1'
    assert trades[0]['realized_pnl'] == Decimal('30')


def test_valid_enum_values_are_kept():
    """The check must discriminate, not strip everything that happens to be typed."""
    raw = _wrap(f'<Trades>{_trade(subCategory=None, notes="P", buySell="SELL")}</Trades>')

    sanitized, warnings = _svc()._sanitize_flex_xml(raw)

    assert sanitized is raw  # nothing rejected -> untouched
    assert warnings == []
    trade = _statement(raw).Trades[0]
    assert trade.buySell is enums.BuySell.SELL
    assert trade.notes == (enums.Code.PARTIAL,)


def test_container_attributes_survive_sanitizing():
    """
    ibflex asserts <FlexStatements count> matches the number of children, so
    stripping `count` would break every document. Container tags aren't modelled
    in Types, so they must be left alone even when the pass rewrites the tree.
    """
    sanitized, warnings = _svc()._sanitize_flex_xml(_TRADES)

    assert sanitized is not _TRADES  # the tree really was rewritten
    assert b'count="1"' in sanitized
    _statement(sanitized)  # ibflex's count assertion still passes


def test_sanitizer_never_raises_on_malformed_xml():
    garbage = b'<FlexQueryResponse><not closed'

    sanitized, warnings = _svc()._sanitize_flex_xml(garbage)

    assert sanitized is garbage
    assert warnings == []


# --------------------------------------------------------------------------
# Aggregate-row de-duplication
# --------------------------------------------------------------------------

def test_aggregate_rows_dropped_when_execution_rows_present():
    """An ORDER row restates its EXECUTION fills; ingesting both double-counts."""
    raw = _wrap(
        '<Trades>'
        + _trade(transactionID='TX1', levelOfDetail='EXECUTION')
        + _trade(transactionID='TX2', levelOfDetail='ORDER')
        + _trade(transactionID='TX3', levelOfDetail='SYMBOL_SUMMARY')
        + '</Trades>'
    )

    sanitized, warnings = _svc()._sanitize_flex_xml(raw)

    trades = _statement(sanitized).Trades
    assert [t.transactionID for t in trades] == ['TX1']
    assert any('aggregate <Trade> row(s)' in w for w in warnings)


def test_all_aggregate_rows_are_kept_rather_than_emptying_the_section():
    """No-data-loss rule: if aggregates are all we have, keep them and warn."""
    raw = _wrap(
        '<Trades>'
        + _trade(transactionID='TX2', levelOfDetail='ORDER')
        + _trade(transactionID='TX3', levelOfDetail='ORDER')
        + '</Trades>'
    )

    sanitized, warnings = _svc()._sanitize_flex_xml(raw)

    trades = _statement(sanitized).Trades
    assert [t.transactionID for t in trades] == ['TX2', 'TX3']
    assert any('only aggregate rows' in w for w in warnings)


def test_attribute_counts_exclude_rows_that_were_already_dropped():
    """
    The warnings are the primary diagnostic for schema drift, so their counts must
    describe rows that actually get parsed. Pass 2 used to scrub the pass-1 snapshot,
    which still held the detached aggregate rows — so a sync reporting
    `Trade.subCategory x290` had really only ingested 64 trades.
    """
    raw = _wrap(
        '<Trades>'
        + _trade(transactionID='TX1', levelOfDetail='EXECUTION')
        + _trade(transactionID='TX2', levelOfDetail='ORDER')
        + _trade(transactionID='TX3', levelOfDetail='ORDER')
        + '</Trades>'
    )

    _, warnings = _svc()._sanitize_flex_xml(raw)

    # One surviving row carries subCategory, not all three.
    assert any('Trade.subCategory x1' in w for w in warnings)
    assert not any('Trade.subCategory x3' in w for w in warnings)


def test_rows_without_level_of_detail_are_never_dropped():
    raw = _wrap(
        '<Trades>'
        + _trade(transactionID='TX1', levelOfDetail='ORDER')
        + _trade(transactionID='TX2', levelOfDetail=None)
        + '</Trades>'
    )

    sanitized, _ = _svc()._sanitize_flex_xml(raw)

    trades = _statement(sanitized).Trades
    assert [t.transactionID for t in trades] == ['TX2']
