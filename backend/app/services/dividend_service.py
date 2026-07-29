"""
Dividend Service
Fetches dividend ex-dates from yfinance, computes income from tax lots,
converts to EUR, and provides monthly summary data.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta, date
from decimal import Decimal
from collections import defaultdict
import logging
import random
import asyncio
import yfinance as yf

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import Security
from app.models.taxlot import TaxLot
from app.repositories.dividend_repository import DividendRepository
from app.services.currency_service import CurrencyService
from app.services.dividend_forecast import HistPayment, project_dividends

logger = logging.getLogger(__name__)


class DividendService:
    """Service for fetching and computing dividend income."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DividendRepository(db)
        self.currency_service = CurrencyService(db)

    async def _get_yahoo_ticker(self, security: Security) -> str:
        """Resolve Yahoo ticker for a security (reuses MarketDataService logic)."""
        from app.services.market_data_service import MarketDataService
        market_service = MarketDataService(self.db)
        return await market_service._get_yahoo_ticker(security)

    async def sync_dividend_data(self) -> Dict:
        """Fetch dividend ex-dates from yfinance for all securities."""
        result = await self.db.execute(select(Security))
        securities = list(result.scalars().all())

        if not securities:
            return {'securities_processed': 0, 'dividends_added': 0, 'errors': 0,
                    'message': 'No securities found'}

        logger.info(f"Syncing dividends for {len(securities)} securities")

        dividends_added = 0
        errors = 0
        skipped = 0

        for i, security in enumerate(securities, 1):
            try:
                # Staleness check: skip if we fetched dividends < 7 days ago
                last_fetch = await self.repo.get_last_fetch_time(security.id)
                if last_fetch and (datetime.now() - last_fetch) < timedelta(days=7):
                    skipped += 1
                    continue

                yahoo_ticker = await self._get_yahoo_ticker(security)
                logger.info(f"[{i}/{len(securities)}] Fetching dividends for {security.symbol} ({yahoo_ticker})")

                # Rate limit before API call
                await asyncio.sleep(random.uniform(1.0, 2.0))

                # Fetch dividends in a thread
                def _fetch(ticker=yahoo_ticker):
                    return yf.Ticker(ticker).dividends

                dividends_series = await asyncio.to_thread(_fetch)

                if dividends_series is None or dividends_series.empty:
                    logger.info(f"No dividends found for {security.symbol}")
                    continue

                for dt_index, amount in dividends_series.items():
                    ex_date = dt_index.date() if hasattr(dt_index, 'date') else dt_index
                    await self.repo.upsert_payment({
                        'security_id': security.id,
                        'ex_date': ex_date,
                        'amount_per_share': Decimal(str(amount)),
                        'currency': security.currency,
                        'source': 'yfinance_estimate',
                    })
                    dividends_added += 1

                await self.db.commit()

            except Exception as e:
                logger.error(f"Error fetching dividends for {security.symbol}: {e}")
                errors += 1
                await self.db.rollback()
                continue

        logger.info(f"Dividend sync complete: added={dividends_added}, skipped={skipped}, errors={errors}")
        return {
            'securities_processed': len(securities) - skipped,
            'dividends_added': dividends_added,
            'skipped': skipped,
            'errors': errors,
            'message': f'Synced dividends: {dividends_added} records from {len(securities) - skipped} securities',
        }

    async def compute_dividend_income(self) -> Dict:
        """Compute shares held and EUR amounts for all uncomputed dividend payments."""
        uncomputed = await self.repo.get_uncomputed()
        if not uncomputed:
            return {'computed': 0, 'message': 'All dividends already computed'}

        logger.info(f"Computing income for {len(uncomputed)} dividend payments")

        # Pre-load all tax lots
        taxlot_result = await self.db.execute(select(TaxLot))
        all_taxlots = list(taxlot_result.scalars().all())

        # Group tax lots by security_id
        taxlots_by_security: Dict[int, List[TaxLot]] = defaultdict(list)
        for tl in all_taxlots:
            taxlots_by_security[tl.security_id].append(tl)

        computed = 0
        errors = 0

        for dp in uncomputed:
            try:
                # Authoritative IBKR rows carry gross/withholding/net directly — never
                # recompute them from per-share estimates.
                if dp.source == "ibkr":
                    continue

                # Sum shares held on ex_date: open_date <= ex_date AND (close_date IS NULL OR close_date > ex_date)
                lots = taxlots_by_security.get(dp.security_id, [])
                shares = Decimal("0")
                for lot in lots:
                    if lot.open_date > dp.ex_date:
                        continue
                    if lot.close_date and lot.close_date <= dp.ex_date:
                        continue
                    shares += lot.quantity

                if shares <= 0:
                    # No shares held on ex-date — set to 0 so it's not re-processed
                    dp.shares_held = Decimal("0")
                    dp.gross_amount_eur = Decimal("0")
                    dp.withholding_tax_eur = Decimal("0")
                    dp.net_amount_eur = Decimal("0")
                    dp.last_computed = datetime.now()
                    computed += 1
                    continue

                gross_amount = dp.amount_per_share * shares

                # Convert to EUR
                currency = dp.currency or "USD"
                if currency == "EUR":
                    gross_eur = gross_amount
                else:
                    try:
                        fx_rate = await self.currency_service.get_exchange_rate(
                            currency, dp.ex_date
                        )
                        gross_eur = gross_amount * fx_rate
                    except Exception as e:
                        logger.warning(f"FX conversion failed for {currency} on {dp.ex_date}: {e}")
                        gross_eur = gross_amount  # fallback: store unconverted

                dp.shares_held = shares
                dp.gross_amount_eur = gross_eur
                # yfinance estimates carry no withholding info; net == gross.
                dp.withholding_tax_eur = Decimal("0")
                dp.net_amount_eur = gross_eur
                if dp.source is None:
                    dp.source = "yfinance_estimate"
                dp.last_computed = datetime.now()
                computed += 1

            except Exception as e:
                logger.error(f"Error computing dividend for security_id={dp.security_id}, ex_date={dp.ex_date}: {e}")
                errors += 1
                continue

        await self.db.commit()
        logger.info(f"Dividend computation complete: computed={computed}, errors={errors}")
        return {'computed': computed, 'errors': errors, 'message': f'Computed {computed} dividend payments'}

    async def _to_eur(self, amount: Decimal, currency: str, on_date: date) -> Decimal:
        """Convert an amount to EUR on a date, tolerating unsupported currencies."""
        if not amount:
            return Decimal("0")
        if (currency or "EUR") == "EUR":
            return amount
        try:
            return await self.currency_service.convert_to_eur(
                amount=amount, from_currency=currency, target_date=on_date
            )
        except Exception as e:
            logger.warning(f"Dividend FX conversion failed for {currency} on {on_date}: {e}")
            return amount  # fallback: store unconverted

    async def sync_dividends_from_cash_transactions(
        self, cash_txns: List[Dict], conid_to_security_id: Dict[str, int]
    ) -> Dict:
        """
        Record authoritative dividend income from IBKR <CashTransactions>.

        Groups Dividends + Payment-In-Lieu (gross) and Withholding Tax per
        security per pay date, computes net = gross - withholding, converts to EUR
        at the pay date, and upserts with source='ibkr'. Does NOT commit — the
        caller's sync transaction owns the commit. Tolerant of an empty list.
        """
        if not cash_txns:
            return {"ibkr_dividends": 0, "message": "No dividend cash transactions"}

        conid_map = {str(k): v for k, v in conid_to_security_id.items()}
        grouped: Dict = defaultdict(lambda: {"gross": Decimal("0"), "wht": Decimal("0"), "currency": None})

        for ct in cash_txns:
            security_id = conid_map.get(str(ct["conid"]))
            if not security_id:
                continue
            key = (security_id, ct["pay_date"])
            g = grouped[key]
            g["currency"] = g["currency"] or ct.get("currency")
            if ct["type"] in ("DIVIDEND", "PAYMENTINLIEU"):
                g["gross"] += ct["amount"]
            elif ct["type"] == "WHTAX":
                g["wht"] += ct["amount"]  # IBKR reports withholding as a negative amount

        saved = 0
        now = datetime.now()
        for (security_id, pay_date), g in grouped.items():
            gross = g["gross"]
            if gross <= 0:
                # Only withholding with no matching dividend (e.g. a reclass) — skip.
                continue
            withholding = -g["wht"]  # make positive
            currency = g["currency"] or "USD"

            gross_eur = await self._to_eur(gross, currency, pay_date)
            wht_eur = await self._to_eur(withholding, currency, pay_date)
            net_eur = gross_eur - wht_eur

            await self.repo.upsert_payment({
                "security_id": security_id,
                "ex_date": pay_date,     # unique key; pay date is fine for tax-year bucketing
                "pay_date": pay_date,
                "amount_per_share": None,
                "currency": currency,
                "shares_held": Decimal("0"),  # non-null so compute_dividend_income skips it
                "gross_amount_eur": gross_eur,
                "withholding_tax_eur": wht_eur,
                "net_amount_eur": net_eur,
                "source": "ibkr",
                "last_computed": now,
            })
            saved += 1

        logger.info(f"Recorded {saved} IBKR dividend payment(s) from cash transactions")
        return {"ibkr_dividends": saved, "message": f"Recorded {saved} IBKR dividend payments"}

    @staticmethod
    def _is_income(p) -> bool:
        """
        True when a row represents money actually received.

        yfinance returns a security's ENTIRE dividend history — Coca-Cola pays
        since the 1960s — and compute_dividend_income() writes a zero row for
        every ex-date where no shares were held, deliberately, so it isn't
        reprocessed. Those are bookkeeping, not income: counting them gave the
        summary 439 months back to 1985 of which 419 were empty.
        """
        return ((p.gross_amount_eur or Decimal("0")) > 0
                or (p.net_amount_eur or Decimal("0")) > 0)

    @staticmethod
    def _splice_by_era(payments: List) -> tuple:
        """
        Honest mix of the two sources: yfinance estimates strictly BEFORE the first
        IBKR payment date, authoritative IBKR rows from there on.

        A global "prefer ibkr" switch is wrong in both directions — IBKR rows exist
        only from the date the cash-transaction ledger starts (a YTD Flex Query
        can't reach earlier years), so filtering to ibkr erases all earlier history,
        while keeping estimates inside the IBKR era would double-count the same
        dividend from both sources. Returns (kept_payments, ibkr_from) where
        ibkr_from is None when no IBKR rows exist.
        """
        ibkr_dates = [(p.pay_date or p.ex_date) for p in payments if p.source == "ibkr"]
        if not ibkr_dates:
            return list(payments), None
        boundary = min(ibkr_dates)
        kept = [
            p for p in payments
            if p.source == "ibkr" or (p.pay_date or p.ex_date) < boundary
        ]
        return kept, boundary

    async def get_dividend_summary(self) -> Dict:
        """
        Aggregate computed dividends into a monthly summary (in base currency).

        The history is era-spliced: estimates before the first IBKR payment, real
        IBKR rows from there on (see _splice_by_era — the old global switch dropped
        every pre-IBKR month from the card). Monthly amounts and totals are NET
        of withholding tax; gross and withholding totals are reported separately.
        """
        payments, ibkr_from = self._splice_by_era(await self.repo.get_computed_dividends())
        payments = [p for p in payments if self._is_income(p)]

        # Project EUR amounts into the configured base currency at each date.
        from app.services.portfolio_service import PortfolioService
        base_fx = await PortfolioService(self.db)._load_base_fx()

        monthly: Dict[str, Decimal] = defaultdict(Decimal)
        total_net = Decimal("0")
        total_gross = Decimal("0")
        total_wht = Decimal("0")

        now = datetime.now()
        ytd_net = Decimal("0")

        for p in payments:
            on_date = p.pay_date or p.ex_date
            gross_e = p.gross_amount_eur or Decimal("0")
            net_e = p.net_amount_eur if p.net_amount_eur is not None else gross_e
            wht_e = p.withholding_tax_eur or Decimal("0")

            gross = base_fx.convert(gross_e, on_date)
            net = base_fx.convert(net_e, on_date)
            wht = base_fx.convert(wht_e, on_date)

            month_key = on_date.strftime("%Y-%m")
            monthly[month_key] += net
            total_net += net
            total_gross += gross
            total_wht += wht
            if on_date.year == now.year:
                ytd_net += net

        monthly_list = [
            {"month": k, "amount_eur": round(float(v), 2)}
            for k, v in sorted(monthly.items())
        ]

        last_updated = None
        if payments:
            latest = max((p.last_computed for p in payments if p.last_computed), default=None)
            if latest:
                last_updated = latest.isoformat()

        return {
            "monthly": monthly_list,           # NET per month
            "ytd_eur": round(float(ytd_net), 2),
            "total_eur": round(float(total_net), 2),        # NET (back-compat key)
            "total_gross_eur": round(float(total_gross), 2),
            "total_withholding_eur": round(float(total_wht), 2),
            "total_net_eur": round(float(total_net), 2),
            "source": "ibkr" if ibkr_from else "yfinance_estimate",
            "ibkr_from": ibkr_from.isoformat() if ibkr_from else None,
            "last_updated": last_updated,
            "base_currency": base_fx.base_currency,
        }

    async def get_dividend_breakdown(
        self,
        year: Optional[int] = None,
        include_forecast: bool = True,
        as_of: Optional[date] = None,
    ) -> Dict:
        """
        Dividends grouped by month × symbol plus per-security totals, optionally
        with forecast projections for the months after ``as_of``.

        Reads only cached data — dividend_payments, taxlots, market_prices and
        exchange_rates — never Yahoo or IBKR. The history is era-spliced like the
        summary; forecasts are inferred per held security from its own payout
        cadence and trailing amounts (see dividend_forecast.py). ``as_of`` is
        injectable purely so tests can pin the forecast horizon.
        """
        as_of = as_of or date.today()
        all_payments, ibkr_from = self._splice_by_era(await self.repo.get_computed_dividends())
        # Zero rows (an estimate computed while no shares were held at the ex-date)
        # are bookkeeping, not income — and they would poison the cadence inference.
        all_payments = [p for p in all_payments if self._is_income(p)]

        securities = {
            s.id: s for s in (await self.db.execute(select(Security))).scalars().all()
        }

        from app.services.portfolio_service import PortfolioService
        portfolio = PortfolioService(self.db)
        base_fx = await portfolio._load_base_fx()

        years = sorted({(p.pay_date or p.ex_date).year for p in all_payments} | {as_of.year})

        win_start = date(year, 1, 1) if year is not None else None
        win_end = date(year, 12, 31) if year is not None else None

        def _in_window(d: date) -> bool:
            return (win_start is None or d >= win_start) and (win_end is None or d <= win_end)

        def _new_row() -> Dict:
            return {
                "payouts": 0, "gross": Decimal("0"), "wht": Decimal("0"),
                "net": Decimal("0"), "forecast_payouts": 0,
                "forecast_net": Decimal("0"), "sources": set(),
            }

        def _symbol(security_id: int) -> str:
            sec = securities.get(security_id)
            return sec.symbol if sec else f"#{security_id}"

        monthly_actual: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        monthly_forecast: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        by_sec: Dict[int, Dict] = {}
        total_net = Decimal("0")
        total_forecast = Decimal("0")

        for p in all_payments:
            on_date = p.pay_date or p.ex_date
            if not _in_window(on_date):
                continue
            net = base_fx.convert(p.net_amount_eur, on_date)
            row = by_sec.setdefault(p.security_id, _new_row())
            row["payouts"] += 1
            row["net"] += net
            row["gross"] += base_fx.convert(p.gross_amount_eur or Decimal("0"), on_date)
            row["wht"] += base_fx.convert(p.withholding_tax_eur or Decimal("0"), on_date)
            row["sources"].add("ibkr" if p.source == "ibkr" else "estimate")
            monthly_actual[on_date.strftime("%Y-%m")][_symbol(p.security_id)] += net
            total_net += net

        if include_forecast:
            horizon_start = as_of + timedelta(days=1)
            horizon_end = win_end or date(as_of.year, 12, 31)
            if horizon_start <= horizon_end:
                taxlots = list((await self.db.execute(select(TaxLot))).scalars().all())
                lots_by_sec: Dict[int, List[TaxLot]] = defaultdict(list)
                for tl in taxlots:
                    lots_by_sec[tl.security_id].append(tl)

                def shares_at(sid: int, d: date) -> Decimal:
                    total = Decimal("0")
                    for lot in lots_by_sec.get(sid, []):
                        if lot.open_date > d:
                            continue
                        if lot.close_date and lot.close_date <= d:
                            continue
                        total += lot.quantity
                    return total

                # Full spliced history (not window-filtered): cadence must be
                # inferred from everything known, even when viewing one year.
                hist_by_sec: Dict[int, List[HistPayment]] = defaultdict(list)
                for p in all_payments:
                    on_date = p.pay_date or p.ex_date
                    if on_date > as_of:
                        continue
                    shares = p.shares_held if (p.shares_held and p.shares_held > 0) \
                        else shares_at(p.security_id, on_date)
                    hist_by_sec[p.security_id].append(HistPayment(
                        on_date=on_date, net_eur=p.net_amount_eur,
                        shares_held=shares if shares > 0 else None,
                    ))

                for sid, lots in lots_by_sec.items():
                    qty = shares_at(sid, as_of)
                    if qty <= 0:
                        continue
                    for fp in project_dividends(hist_by_sec.get(sid, []), qty,
                                                horizon_start, horizon_end):
                        if not _in_window(fp.on_date):
                            continue
                        amt = base_fx.convert(fp.net_eur, fp.on_date)
                        row = by_sec.setdefault(sid, _new_row())
                        row["forecast_payouts"] += 1
                        row["forecast_net"] += amt
                        monthly_forecast[fp.on_date.strftime("%Y-%m")][_symbol(sid)] += amt
                        total_forecast += amt

        # Trailing-12-month yield: spliced net over the current market value.
        # Positions are a decoration here — their failure must not 500 the view.
        ttm_start = as_of - timedelta(days=365)
        ttm_net: Dict[int, Decimal] = defaultdict(Decimal)
        for p in all_payments:
            d = p.pay_date or p.ex_date
            if ttm_start <= d <= as_of:
                ttm_net[p.security_id] += base_fx.convert(p.net_amount_eur, d)
        mv_by_sec: Dict[int, Decimal] = {}
        try:
            for pos in await portfolio.get_positions_breakdown():
                mv_by_sec[pos["security_id"]] = Decimal(str(pos["market_value_eur"]))
        except Exception as e:
            logger.warning(f"Dividend breakdown: positions unavailable, yields omitted: {e}")

        if year is not None:
            months_axis = [f"{year:04d}-{m:02d}" for m in range(1, 13)]
        else:
            keys = sorted(set(monthly_actual) | set(monthly_forecast))
            months_axis = []
            if keys:
                y, m = (int(x) for x in keys[0].split("-"))
                last_y, last_m = (int(x) for x in keys[-1].split("-"))
                while (y, m) <= (last_y, last_m):
                    months_axis.append(f"{y:04d}-{m:02d}")
                    y, m = (y, m + 1) if m < 12 else (y + 1, 1)

        months = []
        for mk in months_axis:
            actual = monthly_actual.get(mk, {})
            forecast = monthly_forecast.get(mk, {})
            months.append({
                "month": mk,
                "actual": {s: round(float(v), 2) for s, v in sorted(actual.items())},
                "forecast": {s: round(float(v), 2) for s, v in sorted(forecast.items())},
                "actual_total_eur": round(float(sum(actual.values(), Decimal("0"))), 2),
                "forecast_total_eur": round(float(sum(forecast.values(), Decimal("0"))), 2),
            })

        sec_rows = []
        for sid, row in by_sec.items():
            sec = securities.get(sid)
            mv = mv_by_sec.get(sid)
            ttm = ttm_net.get(sid, Decimal("0"))
            sec_rows.append({
                "security_id": sid,
                "symbol": _symbol(sid),
                "description": (sec.description or sec.symbol) if sec else f"#{sid}",
                "payouts": row["payouts"],
                "gross_eur": round(float(row["gross"]), 2),
                "withholding_eur": round(float(row["wht"]), 2),
                "net_eur": round(float(row["net"]), 2),
                "forecast_payouts": row["forecast_payouts"],
                "forecast_net_eur": round(float(row["forecast_net"]), 2),
                "trailing_yield_pct": (
                    round(float(ttm / mv * 100), 2)
                    if mv and mv > 0 and ttm > 0 else None
                ),
                # Provenance of the ACTUAL rows; None for a forecast-only entry.
                "source": (
                    ("mixed" if len(row["sources"]) > 1 else next(iter(row["sources"])))
                    if row["sources"] else None
                ),
            })
        sec_rows.sort(key=lambda r: r["net_eur"] + r["forecast_net_eur"], reverse=True)

        return {
            "years": years,
            "year": year,
            "months": months,
            "securities": sec_rows,
            "total_net_eur": round(float(total_net), 2),
            "total_forecast_net_eur": round(float(total_forecast), 2),
            "ibkr_from": ibkr_from.isoformat() if ibkr_from else None,
            "base_currency": base_fx.base_currency,
        }
