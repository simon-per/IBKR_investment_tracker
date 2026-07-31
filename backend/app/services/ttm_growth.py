"""
Trailing-twelve-month year-over-year growth from a yfinance quarterly-financials frame.

Shared by ``FundamentalsService`` and ``WatchlistService``. It lived as a private method
on **both**, and the copies had drifted: the watchlist's carried a 5-7-quarter fallback
tier the fundamentals' lacked, and the fundamentals' additionally bailed out on
``quarterly_financials.shape[1] < 8`` — a *column* count, while the tiers measure a
*row's* non-NaN length, so a frame with 8 columns but a sparse row was judged by one
rule and a frame with 6 columns by another. The consequence was visible: the same
security could report different earnings growth on ``/api/fundamentals/portfolio`` and
``/api/watchlist``.

Neither copy touched ``self``, so this is a plain function.
"""
from typing import Optional


def ttm_growth_from_quarterly(quarterly_financials, row_candidates: list) -> Optional[float]:
    """
    YoY growth of a line item, with a tiered fallback:

    - **>= 8 quarters** — ``sum(Q1..Q4)`` against ``sum(Q5..Q8)``. The real TTM
      comparison, and the only tier immune to seasonality.
    - **5-7 quarters** — the same quarter a year earlier (``Q[0]`` vs ``Q[4]``).
      Seasonal, but a recently-listed company has nothing better, and reporting
      *nothing* sends the caller to yfinance's own laggier ``.info`` figure.
    - **< 5 quarters** — no answer from this candidate.

    ``row_candidates`` is a fallback *chain*, tried in order, and a candidate that is
    present but unusable (too few quarters, or a zero base) falls through to the next —
    which is why callers pass e.g. ``['Diluted EPS', 'Basic EPS', 'Net Income']``.
    Returns None once the chain is exhausted, and the caller falls back to ``.info``.

    Returns a fraction (0.15 = +15%), rounded to 4 dp, or None.
    """
    if quarterly_financials is None or quarterly_financials.empty:
        return None

    for row_name in row_candidates:
        if row_name not in quarterly_financials.index:
            continue

        # Columns are newest-first in yfinance's frame; dropna() keeps that order.
        row = quarterly_financials.loc[row_name].dropna()

        if len(row) >= 8:
            current = float(row.iloc[:4].sum())
            prior = float(row.iloc[4:8].sum())
        elif len(row) >= 5:
            current = float(row.iloc[0])
            prior = float(row.iloc[4])
        else:
            continue

        # A zero base makes growth undefined rather than infinite. abs() so a
        # recovery from a loss reads as positive growth rather than inverted.
        if prior == 0:
            continue
        return round((current - prior) / abs(prior), 4)

    return None
