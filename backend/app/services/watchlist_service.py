from typing import Dict, Optional, List
from datetime import datetime, timedelta
import yfinance as yf
import random
import asyncio
import math
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.watchlist_repository import WatchlistRepository


class WatchlistService:
    """Service for managing watchlist items with cached fundamentals and technicals."""

    CACHE_TTL_HOURS = 1

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WatchlistRepository(db)

    def _safe_float(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return round(f, 4)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value) -> Optional[int]:
        if value is None:
            return None
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return int(f)
        except (ValueError, TypeError):
            return None

    def _compute_rsi(self, closes: np.ndarray, period: int = 14) -> Optional[float]:
        """Compute RSI using Wilder's smoothing method."""
        if len(closes) < period + 1:
            return None

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Wilder's smoothing: first average is SMA, then EMA
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    def _compute_buy_score(self, data: Dict) -> Optional[float]:
        """Compute composite 0-100 buy score from valuation, technicals, quality, and analyst data."""

        # --- Valuation (0-25) ---
        peg = data.get("peg_ratio")
        if peg is not None and peg > 0:
            peg_sub = 10 if peg <= 0.5 else 8 if peg <= 1 else 6 if peg <= 1.5 else 4 if peg <= 2 else 2 if peg <= 3 else 0
        else:
            peg_sub = 5

        fwd_pe = data.get("forward_pe")
        trail_pe = data.get("trailing_pe")
        if fwd_pe is not None and trail_pe is not None and trail_pe > 0:
            ratio = fwd_pe / trail_pe
            fwd_pe_sub = 8 if ratio < 0.85 else 6 if ratio < 0.95 else 4 if ratio < 1.1 else 2
        else:
            fwd_pe_sub = 4

        ev = data.get("ev_to_ebitda")
        if ev is not None and ev > 0:
            ev_sub = 7 if ev < 8 else 5 if ev < 12 else 3 if ev < 18 else 1 if ev < 25 else 0
        else:
            ev_sub = 3

        valuation_score = peg_sub + fwd_pe_sub + ev_sub

        # --- Technical timing (0-25) ---
        rsi = data.get("rsi14")
        if rsi is not None:
            rsi_sub = 10 if rsi < 25 else 8 if rsi < 35 else 6 if rsi < 45 else 4 if rsi < 55 else 2 if rsi < 65 else 0
        else:
            rsi_sub = 5

        pct_high = data.get("pct_from_52w_high")
        if pct_high is not None:
            high_sub = 8 if pct_high < -30 else 6 if pct_high < -20 else 4 if pct_high < -10 else 2 if pct_high < -5 else 0
        else:
            high_sub = 4

        pct_ma = data.get("pct_from_ma200")
        if pct_ma is not None:
            ma_sub = 7 if pct_ma < -20 else 5 if pct_ma < -10 else 3 if pct_ma < 0 else 1 if pct_ma < 10 else 0
        else:
            ma_sub = 3

        technical_score = rsi_sub + high_sub + ma_sub

        # --- Quality (0-25) ---
        margin = data.get("profit_margins")
        if margin is not None:
            margin_sub = 9 if margin > 0.25 else 7 if margin > 0.15 else 5 if margin > 0.08 else 3 if margin > 0 else 1
        else:
            margin_sub = 4

        rev_g = data.get("revenue_growth")
        if rev_g is not None:
            rev_sub = 8 if rev_g > 0.25 else 6 if rev_g > 0.10 else 4 if rev_g > 0.05 else 2 if rev_g > 0 else 0
        else:
            rev_sub = 4

        eps_g = data.get("earnings_growth")
        if eps_g is not None:
            eps_sub = 8 if eps_g > 0.25 else 6 if eps_g > 0.10 else 4 if eps_g > 0.05 else 2 if eps_g > 0 else 0
        else:
            eps_sub = 4

        quality_score = margin_sub + rev_sub + eps_sub

        # --- Analyst consensus (0-25) ---
        rating = data.get("analyst_rating")
        rating_map = {"strong_buy": 13, "buy": 10, "hold": 5, "sell": 2, "strong_sell": 0}
        rating_sub = rating_map.get(rating, 6) if rating else 6

        target = data.get("analyst_target")
        price = data.get("current_price")
        if target is not None and price is not None and price > 0:
            upside = (target - price) / price * 100
            upside_sub = 12 if upside > 30 else 10 if upside > 20 else 7 if upside > 10 else 4 if upside > 0 else 0
        else:
            upside_sub = 6

        analyst_score = rating_sub + upside_sub

        total = valuation_score + technical_score + quality_score + analyst_score
        return round(total, 1)

    def _ttm_growth_from_quarterly(self, quarterly_financials, row_candidates: list) -> Optional[float]:
        """TTM YoY growth with tiered fallback:
        ≥8 quarters: sum(Q1-4) vs sum(Q5-8)
        5-7 quarters: same-quarter YoY (Q[0] vs Q[4])
        <5 quarters: returns None (caller falls back to .info)
        """
        if quarterly_financials is None or quarterly_financials.empty:
            return None
        for row_name in row_candidates:
            if row_name in quarterly_financials.index:
                row = quarterly_financials.loc[row_name].dropna()
                if len(row) >= 8:
                    current_ttm = float(row.iloc[:4].sum())
                    prior_ttm = float(row.iloc[4:8].sum())
                    if prior_ttm != 0:
                        return round((current_ttm - prior_ttm) / abs(prior_ttm), 4)
                elif len(row) >= 5:
                    current_q = float(row.iloc[0])
                    prior_q = float(row.iloc[4])
                    if prior_q != 0:
                        return round((current_q - prior_q) / abs(prior_q), 4)
        return None

    async def _fetch_ticker_data(self, yahoo_ticker: str) -> tuple:
        """Fetch .info, .quarterly_financials, 1y history, and forward estimates in a single thread."""
        def _fetch():
            ticker = yf.Ticker(yahoo_ticker)
            info = ticker.info
            try:
                quarterly_financials = ticker.quarterly_financials
            except Exception:
                quarterly_financials = None
            try:
                history = ticker.history(period="1y")
            except Exception:
                history = None
            try:
                revenue_estimate = ticker.revenue_estimate
            except Exception:
                revenue_estimate = None
            try:
                growth_estimates = ticker.growth_estimates
            except Exception:
                growth_estimates = None
            return info, quarterly_financials, history, revenue_estimate, growth_estimates
        return await asyncio.to_thread(_fetch)

    def _filter_outliers(self, closes: np.ndarray) -> np.ndarray:
        """Remove outlier prices (likely currency-mixed data)."""
        if len(closes) == 0:
            return closes
        median = np.median(closes)
        if median <= 0:
            return closes
        mask = (closes >= 0.2 * median) & (closes <= 5.0 * median)
        return closes[mask]

    async def sync_item(self, yahoo_ticker: str, force: bool = False) -> Dict:
        """Fetch and compute all data for a single watchlist ticker."""
        item = await self.repo.get_by_ticker(yahoo_ticker)
        if not item:
            return {}

        # Skip if cache is fresh
        if not force and item.last_synced:
            age = datetime.now() - item.last_synced
            if age < timedelta(hours=self.CACHE_TTL_HOURS):
                print(f"  [CACHE] {yahoo_ticker} is fresh ({age} old), skipping")
                return {}

        print(f"  Fetching data for {yahoo_ticker}...")
        await asyncio.sleep(random.uniform(1.0, 3.0))

        try:
            info, quarterly_financials, history, revenue_estimate, growth_estimates = await self._fetch_ticker_data(yahoo_ticker)
        except Exception as e:
            print(f"  [ERROR] Failed to fetch {yahoo_ticker}: {e}")
            return {"error": str(e)}

        # TTM growth from quarterly financials (always current, no annual lag)
        ttm_rev = self._ttm_growth_from_quarterly(quarterly_financials, ['Total Revenue'])
        ttm_eps = self._ttm_growth_from_quarterly(quarterly_financials, ['Diluted EPS', 'Basic EPS', 'Net Income'])

        # Forward estimates from analyst consensus
        fwd_rev = None
        try:
            if revenue_estimate is not None and '+1y' in revenue_estimate.index:
                fwd_rev = self._safe_float(revenue_estimate.loc['+1y', 'growth'])
        except Exception:
            pass

        fwd_eps = None
        try:
            if growth_estimates is not None and '+1y' in growth_estimates.index:
                fwd_eps = self._safe_float(growth_estimates.loc['+1y', 'stockTrend'])
        except Exception:
            pass

        current_price = self._safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))

        data: Dict = {
            "symbol": info.get("symbol", yahoo_ticker),
            "company_name": info.get("shortName") or info.get("longName"),
            "current_price": current_price,
            "currency": info.get("currency"),
            "data_currency": info.get("currency"),
            "trailing_pe": self._safe_float(info.get("trailingPE")),
            "forward_pe": self._safe_float(info.get("forwardPE")),
            "peg_ratio": self._safe_float(info.get("pegRatio")),
            "ev_to_ebitda": self._safe_float(info.get("enterpriseToEbitda")),
            "revenue_growth": ttm_rev if ttm_rev is not None else self._safe_float(info.get("revenueGrowth")),
            "earnings_growth": ttm_eps if ttm_eps is not None else self._safe_float(info.get("earningsGrowth")),
            "fwd_revenue_growth": fwd_rev,
            "fwd_eps_growth": fwd_eps,
            "profit_margins": self._safe_float(info.get("profitMargins")),
            "market_cap": self._safe_int(info.get("marketCap")),
            "analyst_target": self._safe_float(info.get("targetMeanPrice")),
            "analyst_rating": info.get("recommendationKey"),
            "analyst_count": self._safe_int(info.get("numberOfAnalystOpinions")),
            "last_synced": datetime.now(),
        }

        # If yfinance didn't return pegRatio, compute from trailing PE / 5-year EPS growth
        # Uses longTermGrowth (analyst 5-yr CAGR) to match Yahoo Finance's PEG methodology.
        if data["peg_ratio"] is None and data["trailing_pe"]:
            lt_growth = self._safe_float(info.get("longTermGrowth") or info.get("longTermEpsGrowth"))
            if lt_growth and lt_growth > 0:
                lt_pct = lt_growth * 100 if lt_growth < 1 else lt_growth  # normalise if already a %
                data["peg_ratio"] = self._safe_float(data["trailing_pe"] / lt_pct)

        # Use .info for 52-week high/low and moving averages (reliable, pre-computed)
        data["week52_high"] = self._safe_float(info.get("fiftyTwoWeekHigh"))
        data["week52_low"] = self._safe_float(info.get("fiftyTwoWeekLow"))
        data["ma200"] = self._safe_float(info.get("twoHundredDayAverage"))
        data["ma50"] = self._safe_float(info.get("fiftyDayAverage"))

        # % from 52-week high (using current_price from .info)
        if current_price and data["week52_high"] and data["week52_high"] > 0:
            data["pct_from_52w_high"] = round(
                (current_price - data["week52_high"]) / data["week52_high"] * 100, 2
            )

        # % from 200-day MA (using current_price from .info)
        if current_price and data.get("ma200") and data["ma200"] > 0:
            data["pct_from_ma200"] = round(
                (current_price - data["ma200"]) / data["ma200"] * 100, 2
            )

        # RSI-14: computed from history fetched alongside .info
        try:
            if history is not None and not history.empty and len(history) > 0:
                closes = history["Close"].values.astype(float)
                closes = self._filter_outliers(closes)
                if len(closes) >= 15:
                    data["rsi14"] = self._compute_rsi(closes, period=14)
        except Exception as e:
            print(f"  [WARN] Failed to compute RSI ({yahoo_ticker}): {e}")

        # Compute composite buy score
        data["buy_score"] = self._compute_buy_score(data)

        await self.repo.update_cached_data(item.id, data)
        await self.db.commit()

        print(f"  [OK] Synced {yahoo_ticker}: price={data.get('current_price')}, "
              f"score={data.get('buy_score')}, RSI={data.get('rsi14')}, %52wH={data.get('pct_from_52w_high')}")
        return data

    async def sync_all(self, force: bool = False) -> Dict:
        """Sync all watchlist items."""
        items = await self.repo.get_all()
        if not items:
            return {"synced": 0, "errors": 0, "message": "Watchlist is empty"}

        print(f"\n{'='*60}")
        print(f"Syncing {len(items)} watchlist items")
        print(f"{'='*60}\n")

        synced = 0
        errors = 0

        for i, item in enumerate(items, 1):
            print(f"[{i}/{len(items)}] {item.yahoo_ticker}")
            result = await self.sync_item(item.yahoo_ticker, force=force)
            if "error" in result:
                errors += 1
            else:
                synced += 1

            if i < len(items):
                await asyncio.sleep(random.uniform(2.0, 4.0))

        return {
            "synced": synced,
            "errors": errors,
            "message": f"Synced {synced}/{len(items)} watchlist items",
        }

    async def get_all_items(self) -> List:
        return await self.repo.get_all()
