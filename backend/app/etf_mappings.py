"""
Manual ETF allocation mappings for sector and geographic breakdown.
These percentages are approximate based on ETF holdings and methodology.
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
