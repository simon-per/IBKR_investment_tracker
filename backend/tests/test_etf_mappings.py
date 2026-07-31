"""
Guards on the hand-maintained ETF look-through table (`app/etf_mappings.py`).

`get_portfolio_allocation` distributes an ETF's market value across sectors and
regions using these percentages. Two things make the table worth pinning:

- **A row that does not sum to 100 silently distorts the treemap.** The weights
  are multiplied by the position's own weight, so a column summing to 90 quietly
  shrinks that ETF's contribution and the categories never add up. Nothing in the
  request path checks it, and the numbers are edited by hand.
- **A missing symbol is worse than a wrong one.** `is_known_etf` gates the whole
  look-through, so an unmapped ETF falls through to `security.asset_type` (column
  default `"Stock"`) and to `security.sector`/`security.country`, which Yahoo
  leaves empty for a fund. The holding then appears in *neither* the sector nor
  the geographic breakdown and is labelled a stock in the asset-type one — and no
  sync can repair it, because the missing data is a mapping rather than a fetch.
  That is how SOXQ sat invisible after 2026-07-27.

Offline: pure data, no network.
"""
import pytest

from app.etf_mappings import ETF_ALLOCATIONS, get_etf_allocation, is_known_etf


@pytest.mark.parametrize("symbol", sorted(ETF_ALLOCATIONS))
@pytest.mark.parametrize("dimension", ["sector", "geographic"])
def test_every_breakdown_sums_to_a_hundred(symbol, dimension):
    weights = ETF_ALLOCATIONS[symbol][dimension]
    total = sum(weights.values())
    assert total == pytest.approx(100.0, abs=0.01), (
        f"{symbol} {dimension} sums to {total}, so its share of the treemap is "
        f"scaled by {total / 100:.2f} rather than 1.0"
    )


@pytest.mark.parametrize("symbol", sorted(ETF_ALLOCATIONS))
def test_every_entry_declares_both_dimensions_and_is_marked_an_etf(symbol):
    entry = ETF_ALLOCATIONS[symbol]
    # A missing dimension raises KeyError inside the allocation loop rather than
    # degrading, so absence must fail here instead.
    assert entry["sector"], f"{symbol} has no sector breakdown"
    assert entry["geographic"], f"{symbol} has no geographic breakdown"
    assert entry["asset_type"] == "ETF"


@pytest.mark.parametrize("symbol", sorted(ETF_ALLOCATIONS))
def test_no_weight_is_negative_or_over_a_hundred(symbol):
    for dimension in ("sector", "geographic"):
        for name, pct in ETF_ALLOCATIONS[symbol][dimension].items():
            assert 0 < pct <= 100, f"{symbol} {dimension} {name} is {pct}"


def test_the_semiconductor_funds_held_here_are_both_mapped():
    # SOXQ was bought 2026-07-27 and went unmapped, which is the failure this
    # file's docstring describes. SMH was already present.
    assert is_known_etf("SOXQ")
    assert is_known_etf("SMH")
    # Both are pure-play semiconductor funds, so neither should have picked up a
    # non-technology sector by a copy-paste slip.
    for symbol in ("SOXQ", "SMH"):
        assert get_etf_allocation(symbol)["sector"] == {"Technology": 100.0}


def test_an_unmapped_symbol_reports_itself_rather_than_guessing():
    # The caller branches on `is_known_etf`, so the None is the contract.
    assert not is_known_etf("NOT_AN_ETF")
    assert get_etf_allocation("NOT_AN_ETF") is None
