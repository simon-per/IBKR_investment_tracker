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
from app.repositories.dividend_repository import DividendRepository
from app.services.currency_service import CurrencyService
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

        # --- Dividend income (prefer authoritative IBKR rows with withholding) ---
        div_repo = DividendRepository(self.db)
        use_ibkr = await div_repo.has_ibkr_dividends()
        stmt = (
            select(DividendPayment, Security)
            .join(Security, DividendPayment.security_id == Security.id)
            .where(DividendPayment.gross_amount_eur.isnot(None))
        )
        if use_ibkr:
            stmt = stmt.where(DividendPayment.source == "ibkr")
        rows = (await self.db.execute(stmt)).all()

        dividend_income: List[Dict] = []
        div_gross = div_wht = div_net = Decimal("0")
        for dp, sec in rows:
            on_date = dp.pay_date or dp.ex_date
            if on_date is None or on_date < start or on_date > end:
                continue
            gross_e = dp.gross_amount_eur or Decimal("0")
            wht_e = dp.withholding_tax_eur or Decimal("0")
            net_e = dp.net_amount_eur if dp.net_amount_eur is not None else gross_e
            gross = base_fx.convert(gross_e, on_date)
            wht = base_fx.convert(wht_e, on_date)
            net = base_fx.convert(net_e, on_date)
            div_gross += gross
            div_wht += wht
            div_net += net
            dividend_income.append({
                "symbol": sec.symbol,
                "description": sec.description,
                "isin": sec.isin,
                "pay_date": on_date.isoformat(),
                "gross": round(float(gross), 2),
                "withholding": round(float(wht), 2),
                "net": round(float(net), 2),
            })
        dividend_income.sort(key=lambda d: d["pay_date"])

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

        # --- Indicative year-end holdings (wealth-tax base) ---
        # Uses the current positions snapshot; exact for the current year and
        # indicative for past years (historical valuation is not reconstructed).
        holdings: List[Dict] = []
        holdings_total = Decimal("0")
        try:
            positions = await portfolio.get_positions_breakdown()
            for p in positions:
                mv = Decimal(str(p.get("market_value_eur", 0) or 0))
                holdings_total += mv
                holdings.append({
                    "symbol": p.get("symbol"),
                    "quantity": p.get("quantity"),
                    "market_value": round(float(mv), 2),
                    "cost_basis": round(float(p.get("cost_basis_eur", 0) or 0), 2),
                })
        except Exception:
            pass

        return {
            "year": year,
            "base_currency": base_fx.base_currency,
            "dividend_source": "ibkr" if use_ibkr else "yfinance_estimate",
            "dividend_income": dividend_income,
            "dividend_totals": {
                "gross": round(float(div_gross), 2),
                "withholding": round(float(div_wht), 2),
                "net": round(float(div_net), 2),
            },
            "realized_gains": realized_gains,
            "realized_totals": {
                "proceeds": round(float(r_proceeds), 2),
                "cost_basis": round(float(r_cost), 2),
                "gain_loss": round(float(r_gain), 2),
            },
            "holdings_snapshot": holdings,
            "holdings_snapshot_total": round(float(holdings_total), 2),
            "holdings_snapshot_note": (
                "Current positions snapshot — exact for the current year, "
                "indicative for prior years (year-end valuation not reconstructed)."
            ),
        }

    def to_csv(self, report: Dict) -> str:
        cur = report["base_currency"]
        buf = io.StringIO()
        w = csv.writer(buf)

        w.writerow([f"Tax report {report['year']} — all amounts in {cur}"])
        w.writerow([])

        w.writerow([f"Dividend income (source: {report['dividend_source']})"])
        w.writerow(["Symbol", "Description", "ISIN", "Pay date",
                    f"Gross ({cur})", f"Withholding ({cur})", f"Net ({cur})"])
        for d in report["dividend_income"]:
            w.writerow([d["symbol"], d["description"], d["isin"], d["pay_date"],
                        d["gross"], d["withholding"], d["net"]])
        dt = report["dividend_totals"]
        w.writerow(["TOTAL", "", "", "", dt["gross"], dt["withholding"], dt["net"]])
        w.writerow([])

        w.writerow(["Realized capital gains"])
        w.writerow(["Symbol", "Trade date", "Quantity",
                    f"Proceeds ({cur})", f"Cost basis ({cur})", f"Gain/Loss ({cur})"])
        for r in report["realized_gains"]:
            w.writerow([r["symbol"], r["trade_date"], r["quantity"],
                        r["proceeds"], r["cost_basis"], r["gain_loss"]])
        rt = report["realized_totals"]
        w.writerow(["TOTAL", "", "", rt["proceeds"], rt["cost_basis"], rt["gain_loss"]])
        w.writerow([])

        w.writerow(["Holdings snapshot (indicative wealth-tax base)"])
        w.writerow(["Symbol", "Quantity", f"Market value ({cur})", f"Cost basis ({cur})"])
        for h in report["holdings_snapshot"]:
            w.writerow([h["symbol"], h["quantity"], h["market_value"], h["cost_basis"]])
        w.writerow(["TOTAL", "", report["holdings_snapshot_total"], ""])

        return buf.getvalue()
