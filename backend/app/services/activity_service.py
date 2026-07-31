"""
The account's transaction ledger: trades, corporate actions, cash flows and dividends
in one chronological list.

All four tables were ingested, reconciled, and depended on — the tax report reads
`trades`, the contributions splice reads `cash_flows`, reconciliation reads
`corporate_actions` — while none of them had any read surface at all. Three
consequences, in rising order of seriousness:

- No answer to "what actually happened on this date", which is the first thing anyone
  asks of a portfolio tool.
- The realized-gain figures on the Tax tab had no supporting detail anywhere.
- **The transfer audit CLAUDE.md prescribes was an ssh command.** An incoming transfer
  booked as an ordinary deposit shows up as a portfolio-sized fake contribution, which
  is the highest-risk number in the whole app, and the only way to eyeball the rows was
  `python -m app.cli.manage_cash_flows list` on the VPS. So every cash flow here carries
  its `flow_type` and an explicit `counts_as_money_in` flag.

Money is stored in EUR throughout the pipeline and projected into the base currency at
read time by `BaseFx`, exactly as every other read endpoint does — each row at **its
own date**, so a two-year-old trade is not restated at today's rate.
"""
import csv
import io
import logging
from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_flow import DEPOSIT_WITHDRAW
from app.models.security import Security
from app.repositories.cash_flow_repository import CashFlowRepository
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.dividend_repository import DividendRepository
from app.repositories.trade_repository import TradeRepository

logger = logging.getLogger(__name__)

TRADE = "trade"
DIVIDEND = "dividend"
CASH_FLOW = "cash_flow"
CORPORATE_ACTION = "corporate_action"

KINDS = (TRADE, DIVIDEND, CASH_FLOW, CORPORATE_ACTION)

# Bounds one response. The UI pages; this stops an anonymous caller asking for the
# whole ledger at once, the same reasoning as the 5-year cap on value-over-time.
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


@dataclass
class ActivityRow:
    """
    One event, in the shape every kind can fill.

    Fields that do not apply to a kind are None rather than 0: a corporate action has
    no price, and rendering 0.00 would assert one.
    """
    date: str
    kind: str
    subtype: str                      # BUY/SELL, DEPOSITWITHDRAW, FORWARDSPLIT, ibkr...
    symbol: Optional[str]
    description: str
    quantity: Optional[float]
    price: Optional[float]
    currency: Optional[str]
    # Signed, in the base currency: money leaving the account is negative.
    amount_base: Optional[float]
    realized_pnl_base: Optional[float]
    # Cash flows only. The transfer-vs-deposit distinction the contributions
    # figure hinges on, surfaced rather than left to a CLI.
    counts_as_money_in: Optional[bool]
    # Dividends only: 'ibkr' (real withholding) or 'yfinance_estimate' (a guess).
    source: Optional[str]
    ib_key: Optional[str]


def _f(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def _csv_num(value: Optional[float]) -> str:
    """Empty for a missing figure, never 0.00 — a corporate action has no price, and
    writing a zero would assert one."""
    return "" if value is None else f"{value:.2f}"


class ActivityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_activity(
        self,
        start_date: date,
        end_date: date,
        kinds: Optional[Sequence[str]] = None,
        symbol: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Dict:
        """
        Events in `[start_date, end_date]`, newest first.

        Filtering and paging happen **after** the union rather than per table: the four
        sources are separately ordered, so a per-table limit would silently drop, say,
        every dividend in a busy trading month. The row counts here are hundreds, not
        millions, so assembling then slicing is both correct and cheap.
        """
        # Imported here rather than at module scope: portfolio_service imports plenty
        # and a top-level import would make this module part of that cycle.
        from app.services.portfolio_service import PortfolioService

        base_fx = await PortfolioService(self.db)._load_base_fx()
        wanted = set(kinds) if kinds else set(KINDS)

        rows: List[ActivityRow] = []
        if TRADE in wanted:
            rows.extend(await self._trades(start_date, end_date, base_fx))
        if CASH_FLOW in wanted:
            rows.extend(await self._cash_flows(start_date, end_date, base_fx))
        if CORPORATE_ACTION in wanted:
            rows.extend(await self._corporate_actions(start_date, end_date, base_fx))
        if DIVIDEND in wanted:
            rows.extend(await self._dividends(start_date, end_date, base_fx))

        if symbol:
            needle = symbol.strip().upper()
            rows = [r for r in rows if (r.symbol or "").upper() == needle]

        # Newest first, and deterministic within a date: ib_key breaks ties so paging
        # cannot show the same row twice or skip one when two events share a date.
        rows.sort(key=lambda r: (r.date, r.ib_key or "", r.kind), reverse=True)

        total = len(rows)
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        page = rows[offset:offset + limit]

        return {
            "items": [asdict(r) for r in page],
            "total": total,
            "limit": limit,
            "offset": offset,
            "base_currency": base_fx.base_currency,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

    async def _trades(self, start: date, end: date, base_fx) -> List[ActivityRow]:
        trades = await TradeRepository(self.db).get_between(start, end)
        out = []
        for t in trades:
            # `proceeds` already carries IBKR's sign: negative for a buy (cash out),
            # positive for a sell. Commission is separately signed (negative), so the
            # net cash effect is the sum.
            proceeds = t.proceeds or Decimal("0")
            commission = t.commission or Decimal("0")
            out.append(ActivityRow(
                date=t.trade_date.isoformat(),
                kind=TRADE,
                subtype=t.buy_sell or "",
                symbol=t.symbol,
                description=f"{t.buy_sell or 'TRADE'} {abs(t.quantity)} {t.symbol or ''}".strip(),
                quantity=_f(t.quantity),
                price=_f(t.price),
                currency=t.currency,
                amount_base=_f(base_fx.convert(proceeds + commission, t.trade_date)),
                realized_pnl_base=_f(
                    base_fx.convert(t.realized_pnl, t.trade_date)
                    if t.realized_pnl is not None else None
                ),
                counts_as_money_in=None,
                source=None,
                ib_key=t.ib_key,
            ))
        return out

    async def _cash_flows(self, start: date, end: date, base_fx) -> List[ActivityRow]:
        flows = await CashFlowRepository(self.db).get_between(start, end)
        out = []
        for f in flows:
            is_deposit = f.flow_type == DEPOSIT_WITHDRAW
            out.append(ActivityRow(
                date=f.flow_date.isoformat(),
                kind=CASH_FLOW,
                subtype=f.flow_type,
                symbol=None,
                description=f.description or f.flow_type,
                quantity=None,
                price=None,
                currency=f.currency,
                amount_base=_f(base_fx.convert(f.amount_eur, f.flow_date)),
                realized_pnl_base=None,
                # The whole reason this endpoint exists. A transfer moves capital saved
                # elsewhere years earlier and its lots already carry their own open_date,
                # so counting it would both invent savings and double-count purchases.
                counts_as_money_in=is_deposit,
                source=None,
                ib_key=f.ib_key,
            ))
        return out

    async def _corporate_actions(self, start: date, end: date, base_fx) -> List[ActivityRow]:
        actions = await CorporateActionRepository(self.db).get_between(start, end)
        out = []
        for a in actions:
            out.append(ActivityRow(
                date=a.action_date.isoformat(),
                kind=CORPORATE_ACTION,
                subtype=a.action_type,
                symbol=a.symbol,
                # The raw actionDescription is the useful text (ratios, new symbols);
                # fall back to the enum name when IBKR sent none.
                description=a.description or a.action_type,
                quantity=_f(a.quantity),
                price=None,
                currency=a.currency,
                # Usually zero — a split moves no cash. Non-zero for cash-in-lieu.
                amount_base=_f(
                    base_fx.convert(a.proceeds, a.action_date)
                    if a.proceeds is not None else None
                ),
                realized_pnl_base=None,
                counts_as_money_in=None,
                source=None,
                ib_key=a.ib_key,
            ))
        return out

    async def _dividends(self, start: date, end: date, base_fx) -> List[ActivityRow]:
        """
        Dividends, dated by the day the money moved where that is known.

        yfinance rows are stored under the ex-date and IBKR rows under the **pay** date
        — the divergence that forced the source-aware key on `dividend_payments`. A
        ledger is about when cash moved, so pay_date wins where it exists.

        Zero rows are excluded on the same test the two dividend readers use: yfinance
        returns a security's whole history, most of it predating ownership.
        """
        payments = await DividendRepository(self.db).get_between(start, end)
        symbols = await self._symbols_by_id()
        out = []
        for p in payments:
            gross = p.gross_amount_eur or Decimal("0")
            # Rows predating the withholding-fields migration carry a NULL net; gross is
            # the honest stand-in, matching DividendService._net_eur.
            net = p.net_amount_eur if p.net_amount_eur is not None else gross
            if not (gross > 0 or (net or 0) > 0):
                continue

            when = p.pay_date or p.ex_date
            withholding = p.withholding_tax_eur or Decimal("0")
            out.append(ActivityRow(
                date=when.isoformat(),
                kind=DIVIDEND,
                subtype=p.source or "",
                symbol=symbols.get(p.security_id),
                description=(
                    f"Dividend {symbols.get(p.security_id) or ''}".strip()
                    + (f" (withholding {withholding})" if withholding else "")
                ),
                quantity=_f(p.shares_held) or None,
                price=_f(p.amount_per_share),
                currency=p.currency,
                amount_base=_f(base_fx.convert(net, when)),
                realized_pnl_base=None,
                counts_as_money_in=None,
                # 'yfinance_estimate' is a gross guess with no withholding; badging it
                # is the same honesty flag the tax report and dividends card carry.
                source=p.source,
                # Dividends have no IBKR transaction id of their own here; a stable
                # synthetic key keeps the sort deterministic and the UI keys unique.
                ib_key=f"div-{p.security_id}-{p.source or 'na'}-{p.ex_date.isoformat()}",
            ))
        return out

    @staticmethod
    def to_csv(result: Dict) -> str:
        """
        The page as CSV, for a spreadsheet or an accountant.

        `csv.writer` rather than string joining: descriptions come from IBKR's
        `actionDescription`, which contains commas routinely and quotes occasionally,
        and hand-rolled joining would corrupt exactly the rows that matter most.
        """
        buffer = io.StringIO()
        # QUOTE_MINIMAL with an explicit \n: Excel accepts it, and the default \r\n
        # would double up once the response goes through a text media type.
        writer = csv.writer(buffer, lineterminator="\n")

        base = result.get("base_currency", "EUR")
        writer.writerow([
            "date", "kind", "subtype", "symbol", "description", "quantity", "price",
            "currency", f"amount_{base.lower()}", f"realized_pnl_{base.lower()}",
            "counts_as_money_in", "source",
        ])
        for row in result["items"]:
            writer.writerow([
                row["date"], row["kind"], row["subtype"], row["symbol"] or "",
                row["description"], _csv_num(row["quantity"]), _csv_num(row["price"]),
                row["currency"] or "", _csv_num(row["amount_base"]),
                _csv_num(row["realized_pnl_base"]),
                "" if row["counts_as_money_in"] is None else str(row["counts_as_money_in"]).lower(),
                row["source"] or "",
            ])
        return buffer.getvalue()

    async def _symbols_by_id(self) -> Dict[int, str]:
        # Queried directly rather than through SecurityRepository.get_all(), whose
        # signature carries a default `limit=100` — silently truncating the symbol map
        # would leave the newest holdings' dividends unlabelled.
        result = await self.db.execute(select(Security.id, Security.symbol))
        return {row[0]: row[1] for row in result.all()}
