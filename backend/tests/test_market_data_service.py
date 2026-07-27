from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import market_data_service as mds
from app.services.market_data_service import MarketDataService


class FakeTickerMappingRepository:
    def __init__(self, mappings=None):
        self.mappings = mappings or {}
        self.saved = []

    async def get_mapping(self, ibkr_symbol: str, ibkr_exchange: str):
        return self.mappings.get((ibkr_symbol, ibkr_exchange))

    async def upsert_mapping(self, **kwargs):
        self.saved.append(kwargs)


def make_service(mappings=None) -> MarketDataService:
    service = MarketDataService.__new__(MarketDataService)
    service.ticker_mapping_repo = FakeTickerMappingRepository(mappings)
    return service


def make_security(symbol="SBI", exchange="TSE", currency="CAD"):
    return SimpleNamespace(symbol=symbol, exchange=exchange, currency=currency)


@pytest.mark.asyncio
async def test_tse_cad_uses_toronto_yahoo_suffix():
    service = make_service()
    security = make_security(currency="CAD")

    assert await service._get_yahoo_ticker(security) == "SBI.TO"

    variations = service._get_yahoo_ticker_variations(security)
    assert variations[0] == "SBI.TO"
    assert "SBI.T" not in variations


@pytest.mark.asyncio
async def test_tse_jpy_still_uses_tokyo_yahoo_suffix():
    service = make_service()
    security = make_security(currency="JPY")

    assert await service._get_yahoo_ticker(security) == "SBI.T"

    variations = service._get_yahoo_ticker_variations(security)
    assert variations[0] == "SBI.T"
    assert "SBI.TO" not in variations


@pytest.mark.asyncio
async def test_manual_ticker_mapping_overrides_tse_currency_logic():
    service = make_service({
        ("SBI", "TSE"): SimpleNamespace(yahoo_ticker="SBI.CA"),
    })

    assert await service._get_yahoo_ticker(make_security()) == "SBI.CA"


def test_to_suffix_infers_cad_price_currency():
    service = make_service()

    assert service._get_currency_from_ticker("SBI.TO", make_security()) == "CAD"


@pytest.mark.asyncio
async def test_twse_resolves_to_taiwan_yahoo_suffix():
    """TSMC arrived on a exchange nobody had held before; without TWSE in the table
    the suffix resolves to '' and we fall through to the bare-symbol trap."""
    service = make_service()
    security = make_security(symbol="2330", exchange="TWSE", currency="TWD")

    assert await service._get_yahoo_ticker(security) == "2330.TW"
    assert service._get_currency_from_ticker("2330.TW", security) == "TWD"


# --- the currency guard on auto-discovery ------------------------------------------


def _install_fake_yahoo(monkeypatch, responses):
    """Route yf.Ticker(...).history() through `responses`: {ticker: (close, currency)}."""
    monkeypatch.setattr(mds.random, "uniform", lambda *_: 0)

    class FakePriceHistory:
        def __init__(self):
            self._history_metadata = None

    class FakeTicker:
        def __init__(self, ticker):
            self._ticker = ticker
            self._price_history = FakePriceHistory()

        @property
        def history_metadata(self):
            # yfinance's public property re-requests at an intraday interval when
            # 'tradingPeriods' is absent, which a daily history() never sets. Touching
            # it would double our Yahoo traffic, so failing loudly here keeps that
            # regression from slipping back in.
            raise AssertionError("history_metadata issues a second Yahoo request")

        def history(self, **kwargs):
            entry = responses.get(self._ticker)
            if entry is None:
                return pd.DataFrame()
            close, currency = entry
            self._price_history._history_metadata = {"currency": currency}
            return pd.DataFrame(
                {"Close": [close]},
                index=pd.to_datetime(["2026-07-24"]),
            )

    monkeypatch.setattr(mds.yf, "Ticker", FakeTicker)


@pytest.mark.asyncio
async def test_price_currency_comes_from_yahoo_not_the_ticker_suffix(monkeypatch):
    """Bare `SBI` is a USD instrument. Inference said 'no suffix -> use the security's
    currency' and stamped it CAD, which is what hid the error."""
    _install_fake_yahoo(monkeypatch, {"SBI": (7.70, "USD")})
    service = make_service()

    prices, rate_limited = await service._try_fetch_yahoo(
        "SBI", make_security(), date(2026, 7, 24), date(2026, 7, 24)
    )

    assert rate_limited is False
    assert prices[0]["currency"] == "USD"
    assert prices[0]["close_price"] == Decimal("7.7")


@pytest.mark.asyncio
async def test_variation_quoted_in_another_currency_is_rejected_and_not_saved(monkeypatch):
    """The SBI@TSE regression end to end: the correct .TO ticker returns nothing, the
    bare symbol returns a USD fund. Adopting it overstated the position by 61% and, worse,
    persisted a mapping that shadowed the (correct) suffix logic from then on."""
    _install_fake_yahoo(monkeypatch, {"SBI": (7.70, "USD")})  # SBI.TO deliberately absent
    service = make_service()

    prices = await service.fetch_prices_from_yahoo(
        make_security(), date(2026, 7, 24), date(2026, 7, 24)
    )

    assert prices == []
    assert service.ticker_mapping_repo.saved == []


@pytest.mark.asyncio
async def test_variation_in_the_right_currency_is_still_adopted(monkeypatch):
    """The guard must not break legitimate auto-discovery."""
    _install_fake_yahoo(monkeypatch, {"SBI": (4.78, "CAD")})
    service = make_service()

    prices = await service.fetch_prices_from_yahoo(
        make_security(), date(2026, 7, 24), date(2026, 7, 24)
    )

    assert prices[0]["currency"] == "CAD"
    assert [s["yahoo_ticker"] for s in service.ticker_mapping_repo.saved] == ["SBI"]
