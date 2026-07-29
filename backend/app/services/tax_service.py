"""
Tax Service
Assembles a per-year tax report from authoritative IBKR data, framed for Swiss
filing:
  * Dividend income with foreign withholding tax (DA-1 reclaim) — real figures
    from <CashTransactions> when available, else yfinance-estimated gross.
  * Realized capital gains per SELL trade (Switzerland doesn't tax private
    capital gains, but the figures are provided for completeness / other regimes).
  * A current holdings snapshot as an indicative wealth-tax (Steuerwert) base.

All monetary values are projected into the configured base currency.
"""
import csv
import io
from datetime import date
from decimal import Decimal
from typing import Dict, List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import Security
from app.models.trade import Trade
from app.models.dividend_payment import DividendPayment
from app.services.currency_service import CurrencyService
from app.services.dividend_service import DividendService
from app.services.portfolio_service import PortfolioService


class TaxService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.currency_service = CurrencyService(db)

    async def _to_eur(self, amount: Decimal, currency: str, on_date: date) -> Decimal:
        if not amount:
            return Decimal("0")
        if (currency or "EUR") == "EUR":
            return amount
        try:
            return await self.currency_service.convert_to_eur(
                amount=amount, from_currency=currency, target_date=on_date
            )
        except Exception:
            return amount

    async def get_tax_report(self, year: int) -> Dict:
        start = date(year, 1, 1)
        end = date(year, 12, 31)

        portfolio = PortfolioService(self.db)
        base_fx = await portfolio._load_base_fx()

        # --- Dividend income (era-spliced, like the dividend card) ---
        # The boundary is the globally first IBKR payment: estimates strictly before
        # it, authoritative rows from it on, then windowed to the year below. A
        # per-year boolean dropped every estimate inside the boundary year — real
        # January income vanished from a filing aid that then badged itself
        # authoritative — while a per-year boundary would resurrect the
        # ex-date/pay-date double-count in later years (yfinance stores a dividend
        # under its ex-date, IBKR under its pay date, weeks apart). The two sources
        # are still never summed for the same period.
        stmt = (
            select(DividendPayment, Security)
            .join(Security, DividendPayment.security_id == Security.id)
            .where(DividendPayment.gross_amount_eur.isnot(None))
        )
        all_rows = (await self.db.execute(stmt)).all()
        kept, ibkr_from = DividendService._splice_by_era([dp for dp, _ in all_rows])
        kept_ids = {p.id for p in kept}
        rows = [(dp, sec) for dp, sec in all_rows if dp.id in kept_ids]

        dividend_income: List[Dict] = []
        sources_seen: set = set()
        div_gross = div_wht = div_net = Decimal("0")
        # DA-1 is filed per source country, so accumulate a per-country breakdown as we go.
        by_country: Dict[str, Dict] = {}
        for dp, sec in rows:
            on_date = dp.pay_date or dp.ex_date
            if on_date is None or on_date < start or on_date > end:
                continue
            # yfinance carries a security's whole dividend history, so ex-dates
            # from before it was bought are stored as zero rows. They are not
            # income and must not pad a filing aid: 70 of the 96 rows the 2025
            # report listed were 0.00.
            if not DividendService._is_income(dp):
                continue
            gross_e = dp.gross_amount_eur or Decimal("0")
            wht_e = dp.withholding_tax_eur or Decimal("0")
            net_e = DividendService._net_eur(dp)
            gross = base_fx.convert(gross_e, on_date)
            wht = base_fx.convert(wht_e, on_date)
            net = base_fx.convert(net_e, on_date)
            div_gross += gross
            div_wht += wht
            div_net += net
            row_source = "ibkr" if dp.source == "ibkr" else "yfinance_estimate"
            sources_seen.add(row_source)
            dividend_income.append({
                "symbol": sec.symbol,
                "description": sec.description,
                "isin": sec.isin,
                "pay_date": on_date.isoformat(),
                "gross": round(float(gross), 2),
                "withholding": round(float(wht), 2),
                "net": round(float(net), 2),
                "source": row_source,
            })

            # First two ISIN characters are the issuer's domicile — a good proxy for the
            # withholding country, though not exact (ADRs and some funds differ).
            country = (sec.isin or "")[:2].upper()
            bucket = by_country.setdefault(country or "??", {
                "country": country or "??",
                "gross": Decimal("0"), "withholding": Decimal("0"), "net": Decimal("0"),
                "symbols": set(),
            })
            bucket["gross"] += gross
            bucket["withholding"] += wht
            bucket["net"] += net
            if sec.symbol:
                bucket["symbols"].add(sec.symbol)

        dividend_income.sort(key=lambda d: d["pay_date"])

        dividend_by_country = sorted(
            (
                {
                    "country": b["country"],
                    "gross": round(float(b["gross"]), 2),
                    "withholding": round(float(b["withholding"]), 2),
                    "net": round(float(b["net"]), 2),
                    "positions": len(b["symbols"]),
                }
                for b in by_country.values()
            ),
            key=lambda d: d["withholding"],
            reverse=True,
        )

        # --- Realized capital gains (per SELL trade) ---
        trade_rows = (await self.db.execute(
            select(Trade, Security)
            .join(Security, Trade.security_id == Security.id, isouter=True)
            .where(and_(Trade.trade_date >= start, Trade.trade_date <= end))
            .order_by(Trade.trade_date.asc())
        )).all()

        realized_gains: List[Dict] = []
        r_proceeds = r_cost = r_gain = Decimal("0")
        for t, sec in trade_rows:
            if (t.buy_sell or "").upper() != "SELL":
                continue
            proceeds_e = await self._to_eur(t.proceeds or Decimal("0"), t.currency, t.trade_date)
            gain_e = await self._to_eur(t.realized_pnl or Decimal("0"), t.currency, t.trade_date)
            cost_e = proceeds_e - gain_e
            proceeds = base_fx.convert(proceeds_e, t.trade_date)
            gain = base_fx.convert(gain_e, t.trade_date)
            cost = base_fx.convert(cost_e, t.trade_date)
            r_proceeds += proceeds
            r_cost += cost
            r_gain += gain
            realized_gains.append({
                "symbol": t.symbol or (sec.symbol if sec else None),
                "trade_date": t.trade_date.isoformat(),
                "quantity": float(abs(t.quantity)) if t.quantity is not None else None,
                "proceeds": round(float(proceeds), 2),
                "cost_basis": round(float(cost), 2),
                "gain_loss": round(float(gain), 2),
            })

        realized_source = "trades"
        if not realized_gains:
            # No authoritative SELL trade in this year — either <Trades> hasn't been
            # ingested yet, or the statement period doesn't reach back this far. Fall
            # back to the same market-price approximation over closed lots that the
            # portfolio view uses, so the two never disagree; flagged so the UI can
            # label it an estimate (mirrors dividend_source).
            realized_source = "closed_lot_estimate"
            for row in await portfolio.realized_rows_from_closed_lots(base_fx, start, end):
                proceeds, cost = row["proceeds"], row["cost_basis"]
                gain = proceeds - cost
                r_proceeds += proceeds
                r_cost += cost
                r_gain += gain
                realized_gains.append({
                    "symbol": row["symbol"],
                    "trade_date": row["close_date"].isoformat(),
                    "quantity": float(abs(row["quantity"])) if row["quantity"] is not None else None,
                    "proceeds": round(float(proceeds), 2),
                    "cost_basis": round(float(cost), 2),
                    "gain_loss": round(float(gain), 2),
                })

        # --- Year-end holdings (wealth-tax base / Steuerwert) ---
        # Switzerland values wealth at 31 December, so a past year must be reconstructed
        # at that date rather than reported as today's positions. For the current year
        # (no 31 Dec yet) today's snapshot is the right answer.
        today = date.today()
        as_of = end if end < today else today
        holdings: List[Dict] = []
        holdings_total = Decimal("0")
        try:
            for row in await portfolio.holdings_snapshot_as_of(base_fx, as_of):
                mv = row["market_value"]
                holdings_total += mv
                holdings.append({
                    "symbol": row["symbol"],
                    "quantity": float(row["quantity"]),
                    "market_value": round(float(mv), 2),
                    "cost_basis": round(float(row["cost_basis"]), 2),
                })
        except Exception:
            pass

        # The label reflects what actually contributed inside the year window:
        # "mixed" is the boundary year, where estimates cover the weeks before the
        # cash-transaction ledger began mid-year.
        if sources_seen == {"ibkr"}:
            dividend_source = "ibkr"
        elif "ibkr" in sources_seen:
            dividend_source = "mixed"
        else:
            dividend_source = "yfinance_estimate"

        return {
            "year": year,
            "base_currency": base_fx.base_currency,
            "dividend_source": dividend_source,
            "dividend_ibkr_from": ibkr_from.isoformat() if ibkr_from else None,
            "dividend_income": dividend_income,
            "dividend_by_country": dividend_by_country,
            "dividend_country_note": (
                "Country derived from the ISIN prefix (issuer domicile) — a good proxy for the "
                "DA-1 source country, but verify ADRs and funds, whose withholding country can differ."
            ),
            "dividend_totals": {
                "gross": round(float(div_gross), 2),
                "withholding": round(float(div_wht), 2),
                "net": round(float(div_net), 2),
            },
            "realized_gains": realized_gains,
            "realized_source": realized_source,
            "realized_totals": {
                "proceeds": round(float(r_proceeds), 2),
                "cost_basis": round(float(r_cost), 2),
                "gain_loss": round(float(r_gain), 2),
            },
            "holdings_snapshot": holdings,
            "holdings_snapshot_total": round(float(holdings_total), 2),
            "holdings_as_of": as_of.isoformat(),
            "holdings_snapshot_note": (
                f"Holdings as at {as_of.isoformat()}, valued at that date's closing prices"
                + ("." if as_of == end else " (current year — 31 December has not occurred yet).")
                + " Positions whose price could not be resolved near that date are omitted."
            ),
        }

    def to_csv(self, report: Dict) -> str:
        cur = report["base_currency"]
        buf = io.StringIO()
        w = csv.writer(buf)

        w.writerow([f"Tax report {report['year']} — all amounts in {cur}"])
        w.writerow([])

        w.writerow([f"Dividend income (source: {report['dividend_source']})"])
        if report.get("dividend_source") == "mixed" and report.get("dividend_ibkr_from"):
            w.writerow([
                f"Estimates before {report['dividend_ibkr_from']}; "
                f"IBKR actuals with real withholding from there on"
            ])
        w.writerow(["Symbol", "Description", "ISIN", "Pay date",
                    f"Gross ({cur})", f"Withholding ({cur})", f"Net ({cur})"])
        for d in report["dividend_income"]:
            w.writerow([d["symbol"], d["description"], d["isin"], d["pay_date"],
                        d["gross"], d["withholding"], d["net"]])
        dt = report["dividend_totals"]
        w.writerow(["TOTAL", "", "", "", dt["gross"], dt["withholding"], dt["net"]])
        w.writerow([])

        # DA-1 is filed per source country.
        w.writerow(["Withholding by country (DA-1)"])
        w.writerow(["Country", "Positions",
                    f"Gross ({cur})", f"Withholding ({cur})", f"Net ({cur})"])
        for c in report.get("dividend_by_country", []):
            w.writerow([c["country"], c["positions"], c["gross"], c["withholding"], c["net"]])
        w.writerow([])

        w.writerow([f"Realized capital gains (source: {report.get('realized_source', 'trades')})"])
        w.writerow(["Symbol", "Trade date", "Quantity",
                    f"Proceeds ({cur})", f"Cost basis ({cur})", f"Gain/Loss ({cur})"])
        for r in report["realized_gains"]:
            w.writerow([r["symbol"], r["trade_date"], r["quantity"],
                        r["proceeds"], r["cost_basis"], r["gain_loss"]])
        rt = report["realized_totals"]
        w.writerow(["TOTAL", "", "", rt["proceeds"], rt["cost_basis"], rt["gain_loss"]])
        w.writerow([])

        w.writerow([f"Holdings snapshot (wealth-tax base) as at {report.get('holdings_as_of', '')}"])
        w.writerow(["Symbol", "Quantity", f"Market value ({cur})", f"Cost basis ({cur})"])
        for h in report["holdings_snapshot"]:
            w.writerow([h["symbol"], h["quantity"], h["market_value"], h["cost_basis"]])
        w.writerow(["TOTAL", "", report["holdings_snapshot_total"], ""])

        return buf.getvalue()
