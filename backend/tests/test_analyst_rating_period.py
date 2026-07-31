"""
Picking the right row out of yfinance's recommendations frame.

`_fetch_rating_for_security` took `recommendations.iloc[0]` under a comment
asserting that row 0 *is* the current month. That is provider ordering taken on
trust — the same shape as the `openDateTime` defect CLAUDE.md tells you not to
reintroduce, where data was matched back by index position instead of by the field
that identifies it, and one stray row shifted everything after it.

The consequence here would be quiet: a three-month-old consensus reported as
current is a perfectly plausible number, so nothing on screen looks wrong.

Offline: pandas frames only, no network.
"""

import logging

import pandas as pd
import pytest

from app.models.analyst_rating import AnalystRating
from app.services.analyst_rating_service import CURRENT_PERIOD, _count, select_current_period


def frame(rows):
    """rows: list of (period, strongBuy, buy, hold, sell, strongSell)."""
    return pd.DataFrame(
        rows, columns=['period', 'strongBuy', 'buy', 'hold', 'sell', 'strongSell']
    )


class TestSelectCurrentPeriod:
    def test_picks_the_current_month_row(self):
        df = frame([('0m', 10, 5, 2, 0, 0), ('-1m', 1, 1, 1, 1, 1)])
        assert select_current_period(df)['strongBuy'] == 10

    def test_picks_it_even_when_it_is_not_first(self):
        # The whole point: positional access returns the -3m row here.
        df = frame([
            ('-3m', 1, 1, 1, 1, 1),
            ('-2m', 2, 2, 2, 2, 2),
            ('-1m', 3, 3, 3, 3, 3),
            ('0m', 10, 5, 2, 0, 0),
        ])
        row = select_current_period(df)
        assert row['period'] == CURRENT_PERIOD
        assert row['strongBuy'] == 10

    def test_reports_nothing_rather_than_an_older_period(self, caplog):
        # A stale consensus presented as current is worse than none: it is
        # plausible, so nobody questions it.
        df = frame([('-1m', 3, 3, 3, 3, 3), ('-2m', 2, 2, 2, 2, 2)])
        with caplog.at_level(logging.INFO):
            assert select_current_period(df) is None
        assert "no '0m' row" in caplog.text

    def test_falls_back_to_the_first_row_without_a_period_column(self):
        # A differently-shaped frame is still better read than discarded.
        df = pd.DataFrame([[7, 1, 0, 0, 0]],
                          columns=['strongBuy', 'buy', 'hold', 'sell', 'strongSell'])
        assert select_current_period(df)['strongBuy'] == 7

    @pytest.mark.parametrize("empty", [None, pd.DataFrame()])
    def test_handles_a_missing_or_empty_frame(self, empty):
        assert select_current_period(empty) is None


class TestCount:
    def test_reads_an_ordinary_count(self):
        row = frame([('0m', 12, 4, 1, 0, 0)]).iloc[0]
        assert _count(row, 'strongBuy') == 12

    def test_a_nan_becomes_zero_instead_of_raising(self):
        # `int(nan)` raises, and the caller wraps the whole extraction in a broad
        # `except` — so one unparseable column used to discard all five counts and
        # the security's rating with them.
        row = frame([('0m', float('nan'), 4, 1, 0, 0)]).iloc[0]
        assert _count(row, 'strongBuy') == 0
        assert _count(row, 'buy') == 4

    def test_a_missing_column_is_zero(self):
        row = frame([('0m', 1, 2, 3, 4, 5)]).iloc[0]
        assert _count(row, 'notAColumn') == 0

    def test_a_float_count_is_truncated_not_rejected(self):
        row = pd.DataFrame([[3.0]], columns=['strongBuy']).iloc[0]
        assert _count(row, 'strongBuy') == 3


def test_an_all_zero_frame_cannot_masquerade_as_a_real_consensus():
    """
    Zero is the right reading for a *count within a distribution* — no analysts in
    a bucket is a genuine zero — and this is what keeps that safe: the model already
    refuses to derive a consensus from five zeros, so defaulting to 0 cannot invent
    a rating.
    """
    rating = AnalystRating(
        security_id=1, strong_buy=0, buy=0, hold=0, sell=0, strong_sell=0
    )
    assert rating.total_ratings == 0
    assert rating.consensus == "No Rating"


def test_a_real_distribution_still_produces_a_consensus():
    # (10·1 + 5·2 + 2·3) / 17 = 1.53, just the wrong side of the 1.5 boundary.
    rating = AnalystRating(
        security_id=1, strong_buy=10, buy=5, hold=2, sell=0, strong_sell=0
    )
    assert rating.total_ratings == 17
    assert rating.consensus == "Buy"


def test_the_strong_buy_boundary_is_where_it_claims_to_be():
    # (10·1 + 1·2) / 11 = 1.09, comfortably inside Strong Buy.
    rating = AnalystRating(
        security_id=1, strong_buy=10, buy=1, hold=0, sell=0, strong_sell=0
    )
    assert rating.consensus == "Strong Buy"
