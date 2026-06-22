from types import SimpleNamespace

import pytest

from app.services.market_data_service import MarketDataService


class FakeTickerMappingRepository:
    def __init__(self, mappings=None):
        self.mappings = mappings or {}

    async def get_mapping(self, ibkr_symbol: str, ibkr_exchange: str):
        return self.mappings.get((ibkr_symbol, ibkr_exchange))


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
