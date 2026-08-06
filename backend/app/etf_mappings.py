"""
Manual ETF allocation mappings for sector and geographic breakdown.
These percentages are approximate based on ETF holdings and methodology.

**The two dimensions are not equally well sourced, and the entries say which is which.**
Yahoo's `Ticker(...).funds_data.sector_weightings` returns a real measured sector split for
a fund, so a `sector` block can be copied from it and dated. It exposes **no country or
region weights at all** (`equity_holdings` is valuation ratios, `asset_classes` is
stock/bond/cash) — so every `geographic` block here is hand-derived, and the best available
evidence is `top_holdings`, whose usefulness depends entirely on how much of the fund those
ten names cover. That coverage is recorded per entry, because it is the difference between
a measurement and a guess: GRID's top ten is 59.6% of the fund, QTUM's is 14.9%.

Do not "improve" a geographic block from an ETF's *sector* data or from `.info` — a fund
carries no `country`, which is exactly why the look-through table exists.
"""

ETF_ALLOCATIONS = {
    # iShares Core MSCI World (IWDA)
    "IWDA": {
        "asset_type": "ETF",
        "geographic": {
            "North America": 72.0,
            "Europe": 15.0,
            "Asia Pacific": 10.0,
            "Emerging Markets": 3.0,
        },
        "sector": {
            "Technology": 23.0,
            "Financial Services": 14.0,
            "Healthcare": 12.0,
            "Consumer Cyclical": 11.0,
            "Industrials": 10.0,
            "Communication Services": 8.0,
            "Consumer Defensive": 7.0,
            "Energy": 5.0,
            "Real Estate": 3.0,
            "Utilities": 3.0,
            "Basic Materials": 4.0,
        },
    },

    # Vanguard FTSE All-World (VWCE)
    "VWCE": {
        "asset_type": "ETF",
        "geographic": {
            "North America": 65.0,
            "Europe": 16.0,
            "Asia Pacific": 12.0,
            "Emerging Markets": 7.0,
        },
        "sector": {
            "Technology": 22.0,
            "Financial Services": 15.0,
            "Healthcare": 12.0,
            "Consumer Cyclical": 11.0,
            "Industrials": 11.0,
            "Communication Services": 7.0,
            "Consumer Defensive": 6.0,
            "Energy": 5.0,
            "Basic Materials": 5.0,
            "Real Estate": 3.0,
            "Utilities": 3.0,
        },
    },

    # iShares Core S&P 500 (SXR8)
    "SXR8": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 100.0,
        },
        "sector": {
            "Technology": 30.0,
            "Financial Services": 13.0,
            "Healthcare": 12.0,
            "Consumer Cyclical": 11.0,
            "Communication Services": 9.0,
            "Industrials": 8.0,
            "Consumer Defensive": 6.0,
            "Energy": 4.0,
            "Real Estate": 3.0,
            "Utilities": 2.0,
            "Basic Materials": 2.0,
        },
    },

    # Xtrackers NASDAQ 100 (XNAS)
    "XNAS": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 100.0,
        },
        "sector": {
            "Technology": 55.0,
            "Communication Services": 18.0,
            "Consumer Cyclical": 15.0,
            "Healthcare": 6.0,
            "Industrials": 4.0,
            "Consumer Defensive": 2.0,
        },
    },

    # Xtrackers S&P 500 2x Leveraged (DBPG)
    "DBPG": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 100.0,
        },
        "sector": {
            "Technology": 30.0,
            "Financial Services": 13.0,
            "Healthcare": 12.0,
            "Consumer Cyclical": 11.0,
            "Communication Services": 9.0,
            "Industrials": 8.0,
            "Consumer Defensive": 6.0,
            "Energy": 4.0,
            "Real Estate": 3.0,
            "Utilities": 2.0,
            "Basic Materials": 2.0,
        },
    },

    # VanEck Semiconductor ETF (SMH)
    "SMH": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 60.0,
            "Taiwan": 20.0,
            "Netherlands": 10.0,
            "South Korea": 10.0,
        },
        "sector": {
            "Technology": 100.0,
        },
    },

    # Invesco PHLX Semiconductor ETF (SOXQ)
    #
    # Held since 2026-07-27 and previously unmapped, which is worse than it looks:
    # without an entry here `is_known_etf` is False, so the position falls through
    # to `security.asset_type` — whose column default is "Stock" — and to
    # `security.sector`/`security.country`, which Yahoo leaves empty for a fund.
    # The result was a holding absent from the sector *and* geographic treemaps
    # and counted as a stock in the third, with no sync able to fix it.
    #
    # Approximate, as everywhere in this file. Sector is unambiguous for a pure
    # semiconductor fund; the geography skews more US than SMH because the PHLX
    # SOX index is limited to US-listed names. Adjust if you want it tighter.
    "SOXQ": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 80.0,
            "Taiwan": 10.0,
            "Netherlands": 8.0,
            "South Korea": 2.0,
        },
        "sector": {
            "Technology": 100.0,
        },
    },

    # Xtrackers Artificial Intelligence & Big Data (XAIX)
    "XAIX": {
        "asset_type": "ETF",
        "geographic": {
            "United States": 85.0,
            "Europe": 10.0,
            "Asia Pacific": 5.0,
        },
        "sector": {
            "Technology": 90.0,
            "Communication Services": 7.0,
            "Industrials": 3.0,
        },
    },

    # iShares Core MSCI Emerging Markets IMI (EMIM)
    "EMIM": {
        "asset_type": "ETF",
        "geographic": {
            "China": 30.0,
            "India": 20.0,
            "Taiwan": 17.0,
            "Brazil": 7.0,
            "Saudi Arabia": 5.0,
            "South Africa": 4.0,
            "Other Emerging Markets": 17.0,
        },
        "sector": {
            "Technology": 22.0,
            "Financial Services": 21.0,
            "Consumer Cyclical": 14.0,
            "Communication Services": 10.0,
            "Energy": 8.0,
            "Basic Materials": 8.0,
            "Industrials": 6.0,
            "Healthcare": 5.0,
            "Consumer Defensive": 4.0,
            "Utilities": 2.0,
        },
    },

    # Vanguard Total World Stock (VT) — bought 2026-08-06.
    # Sector: Yahoo funds_data, 2026-08-06 (Technology carries the +0.01 rounding).
    # Geographic: deliberately identical to VWCE above. VT tracks FTSE Global All Cap and
    # VWCE tracks FTSE All-World — the same index family, differing by small-cap inclusion,
    # which barely moves a regional weight. Two funds on one index disagreeing in this
    # table would be this codebase's dominant failure mode in miniature, so they are
    # pinned together on purpose: change one and change the other.
    "VT": {
        "asset_type": "ETF",
        "geographic": {
            "North America": 65.0,
            "Europe": 16.0,
            "Asia Pacific": 12.0,
            "Emerging Markets": 7.0,
        },
        "sector": {
            "Technology": 31.19,
            "Financial Services": 15.72,
            "Industrials": 11.74,
            "Consumer Cyclical": 8.99,
            "Healthcare": 8.31,
            "Communication Services": 7.4,
            "Consumer Defensive": 4.53,
            "Basic Materials": 3.81,
            "Energy": 3.55,
            "Utilities": 2.48,
            "Real Estate": 2.28,
        },
    },

    # First Trust NASDAQ Clean Edge Smart Grid Infrastructure (GRID) — bought 2026-08-06.
    # Sector: Yahoo funds_data, 2026-08-06. Its 0.01 Basic Materials sliver is folded into
    # Industrials rather than kept — a 0.01% category is noise that renders as a treemap
    # tile indistinguishable from a real one.
    # Geographic: derived from top_holdings, which covers **59.6%** of the fund — the
    # strongest basis of the three. Within it the split is 30.2 North America
    # (JCI/ETN/PWR/NVT/HUBB) against 29.4 Europe (Schneider FR, ABB CH, E.ON DE,
    # National Grid GB, Prysmian IT), i.e. almost exactly even. Note JCI, ETN and NVT are
    # Irish plcs counted by their **US listing**, consistent with the rest of this table
    # and with `currencyExposure.ts`: where a thing trades is what we can actually observe.
    # The tail is given a little Asia Pacific, which the measured decile has none of.
    "GRID": {
        "asset_type": "ETF",
        "geographic": {
            "North America": 48.0,
            "Europe": 42.0,
            "Asia Pacific": 10.0,
        },
        "sector": {
            "Industrials": 66.46,
            "Utilities": 18.76,
            "Technology": 11.5,
            "Consumer Cyclical": 3.28,
        },
    },

    # Defiance Quantum (QTUM) — bought 2026-08-06.
    # Sector: Yahoo funds_data, 2026-08-06.
    # Geographic: the weakest block in this file, and flagged rather than dressed up. The
    # top ten covers only **14.9%** of the fund, so it is a thin sample — mitigated, but
    # only partly, by the fund being near equal-weighted (every top holding sits in
    # 1.41-1.62%), which makes that decile more representative of the whole than a
    # cap-weighted fund's would be. Within it: 12.0 North America, 1.5 Asia Pacific
    # (NEC 6701.T), 1.4 Europe (Airbus AIR.PA). The tail of a quantum-computing index
    # carries more Japanese and European names than the head does, so Asia Pacific and
    # Europe are set above their measured share deliberately.
    # If this matters later, replace it with Defiance's own published country weights;
    # that is a real source and this is an estimate.
    "QTUM": {
        "asset_type": "ETF",
        "geographic": {
            "North America": 65.0,
            "Asia Pacific": 20.0,
            "Europe": 15.0,
        },
        "sector": {
            "Technology": 77.75,
            "Industrials": 10.95,
            "Communication Services": 7.16,
            "Consumer Cyclical": 2.76,
            "Healthcare": 1.38,
        },
    },
}


def get_etf_allocation(symbol: str) -> dict:
    """
    Get allocation data for a known ETF.
    Returns None if ETF is not in our mapping.
    """
    return ETF_ALLOCATIONS.get(symbol)


def is_known_etf(symbol: str) -> bool:
    """Check if a symbol is a known ETF in our mappings."""
    return symbol in ETF_ALLOCATIONS
