"""
Coercing a yfinance value into a number, or admitting it is not one.

`.info` fields arrive as floats, numpy scalars, strings, ``None``, and — often
enough to matter — ``NaN``. Every one of those has to become a number or a
``None``; what must never happen is a ``NaN`` reaching the database, where it
compares false against itself and serialises to invalid JSON.

Shared by ``FundamentalsService`` and ``WatchlistService``, which had a private
copy each. `_safe_int` was byte-identical in both; `_safe_float` had already
drifted — the watchlist rounded to four decimals and fundamentals did not — so
the same security's trailing P/E read ``28.453125`` on one endpoint and
``28.4531`` on the other, and after `peg_ratio` was extracted the *same computed
PEG* was displayed to different precision on the two screens.

Both now round to `DISPLAY_DIGITS`. Four decimals is far beyond the precision
Yahoo's own figures carry, so nothing is lost, and it is the behaviour that was
already live on the watchlist.
"""

import math
from typing import Optional

#: Yahoo's ratios and prices carry nothing like this much precision; this exists
#: so two endpoints cannot disagree in the fifth decimal place.
DISPLAY_DIGITS = 4


def safe_float(value, digits: int = DISPLAY_DIGITS) -> Optional[float]:
    """
    ``value`` as a float, or None if it is not a usable number.

    ``NaN`` and infinity become None rather than propagating: a NaN stored in a
    numeric column is not merely wrong, it breaks equality against itself and
    every comparison downstream.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits) if digits is not None else number


def safe_int(value) -> Optional[int]:
    """
    ``value`` as an int, or None if it is not a usable number.

    Truncates rather than rounding, matching the behaviour both copies had —
    these are counts and market caps, where the fractional part is noise from
    the float round-trip rather than information.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(number)
