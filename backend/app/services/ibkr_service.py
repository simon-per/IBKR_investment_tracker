"""
IBKR Flex Query Service
Fetches and parses securities and tax lot data from Interactive Brokers.
Focuses on securities only - ignores dividends, cash, and other transactions.
"""
from typing import List, Dict, Optional
from datetime import datetime, date
from decimal import Decimal
import asyncio
import xml.etree.ElementTree as ET

from ibflex import client, parser, Types, AssetClass

from app.config import settings


class IBKRService:
    """Service for interacting with IBKR Flex Query API"""

    def __init__(self, token: Optional[str] = None, query_id: Optional[str] = None):
        """
        Initialize IBKR service with credentials.

        Args:
            token: IBKR Flex Query token (defaults to settings)
            query_id: IBKR Flex Query ID (defaults to settings)
        """
        self.token = token or settings.ibkr_token
        self.query_id = query_id or settings.ibkr_query_id

    def _fix_currency_codes(self, xml_content: bytes) -> bytes:
        """
        Fix non-standard currency codes in IBKR XML.

        IBKR sometimes uses non-ISO currency codes that the ibflex library rejects.
        This function replaces them with standard ISO codes.

        Args:
            xml_content: Raw XML bytes from IBKR

        Returns:
            Fixed XML bytes with standard currency codes
        """
        # Map of IBKR non-standard codes to ISO standard codes
        currency_fixes = {
            b'RUS': b'RUB',  # Russian Ruble
        }

        fixed_xml = xml_content
        for wrong_code, correct_code in currency_fixes.items():
            # Replace in currency attributes (fromCurrency, toCurrency, currency)
            fixed_xml = fixed_xml.replace(b'fromCurrency="' + wrong_code + b'"', b'fromCurrency="' + correct_code + b'"')
            fixed_xml = fixed_xml.replace(b'toCurrency="' + wrong_code + b'"', b'toCurrency="' + correct_code + b'"')
            fixed_xml = fixed_xml.replace(b'currency="' + wrong_code + b'"', b'currency="' + correct_code + b'"')

        return fixed_xml

    def _extract_open_date_times(self, xml_content: bytes) -> List[Dict]:
        """
        Manually extract openDateTime values from XML since ibflex 0.15 doesn't parse them.

        Returns a list of dicts with position data including openDateTime.
        We'll match by index since ibflex preserves order.
        """
        positions = []

        try:
            root = ET.fromstring(xml_content)
            # Find all OpenPosition elements - order is preserved
            for open_pos in root.findall('.//OpenPosition'):
                conid = open_pos.get('conid')
                open_dt_str = open_pos.get('openDateTime')
                quantity = open_pos.get('position')
                cost_basis_money = open_pos.get('costBasisMoney')
                asset_category = open_pos.get('assetCategory')

                # Only process STK (stocks)
                if asset_category == 'STK' and conid and open_dt_str:
                    try:
                        # Handle both formats: "20251013" and "20251013;112102"
                        if ';' in open_dt_str:
                            open_dt_str = open_dt_str.split(';')[0]  # Take only date part
                        open_dt = datetime.strptime(open_dt_str, '%Y%m%d').date()
                        positions.append({
                            'conid': conid,
                            'quantity': quantity,
                            'cost_basis_money': cost_basis_money,
                            'open_date': open_dt
                        })
                    except ValueError:
                        print(f"WARNING: Could not parse openDateTime '{open_dt_str}' for conid {conid}")
        except Exception as e:
            print(f"WARNING: Error extracting openDateTime from XML: {e}")

        print(f"Extracted {len(positions)} openDateTime values from XML")
        return positions

    async def fetch_flex_data(self) -> Dict:
        """
        Fetch data from IBKR Flex Query API.

        Returns:
            Dict containing parsed statement data with securities, open positions, etc.

        Raises:
            Exception: If API request fails or parsing errors occur
        """
        # Run the blocking ibflex download in a thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            client.download,
            self.token,
            self.query_id
        )

        # Fix non-standard currency codes before parsing
        fixed_response = self._fix_currency_codes(response)

        # Extract openDateTime values before ibflex parsing (since ibflex 0.15 doesn't support it)
        open_date_times = self._extract_open_date_times(fixed_response)

        # Parse the XML response
        try:
            response_obj = parser.parse(fixed_response)
            print(f"\nDEBUG fetch_flex_data: Response type: {type(response_obj)}")
            print(f"DEBUG fetch_flex_data: Response attributes: {[attr for attr in dir(response_obj) if not attr.startswith('_')]}")

            # The response is a FlexQueryResponse, we need to get the FlexStatement from it
            if hasattr(response_obj, 'FlexStatements'):
                flex_statements = response_obj.FlexStatements
                print(f"DEBUG fetch_flex_data: FlexStatements found, count: {len(flex_statements) if flex_statements else 0}")
                statement = flex_statements[0] if flex_statements else None
            else:
                # Fallback: maybe response_obj is already a FlexStatement
                statement = response_obj

            print(f"DEBUG fetch_flex_data: Final statement type: {type(statement)}")
            print(f"DEBUG fetch_flex_data: Statement has OpenPositions: {hasattr(statement, 'OpenPositions')}\n")

        except Exception as e:
            # The ibflex library can be strict about currency codes
            # If parsing still fails, provide a helpful error message
            error_msg = str(e)
            if 'Unknown currency' in error_msg:
                raise ValueError(
                    f"IBKR Flex Query contains unsupported currency codes that the ibflex library cannot parse. "
                    f"Error: {error_msg}. "
                    f"The automatic fix for known currency codes (RUS->RUB) did not resolve this. "
                    f"Please contact support or check for other non-standard currency codes."
                )
            # Re-raise other parsing errors
            raise

        return {
            'statement': statement,
            'account_id': statement.accountId if hasattr(statement, 'accountId') else None,
            'from_date': statement.fromDate if hasattr(statement, 'fromDate') else None,
            'to_date': statement.toDate if hasattr(statement, 'toDate') else None,
            'open_date_times': open_date_times,  # Include manually extracted openDateTime values
        }

    async def extract_securities(self, flex_data: Dict) -> List[Dict]:
        """
        Extract unique securities from Flex Query data.
        Only includes stocks (STK) - filters out options, futures, etc.

        Args:
            flex_data: Parsed flex query data from fetch_flex_data()

        Returns:
            List of security dictionaries with normalized data
        """
        statement = flex_data['statement']
        securities = {}

        print(f"\n=== DEBUGGING STATEMENT ===")
        print(f"DEBUG: Statement type: {type(statement)}")
        print(f"DEBUG: Statement attributes: {[attr for attr in dir(statement) if not attr.startswith('_')]}")
        print(f"DEBUG: Statement has OpenPositions: {hasattr(statement, 'OpenPositions')}")
        print("===========================\n")

        # Get securities info from the SecuritiesInfo section
        if hasattr(statement, 'SecuritiesInfo') and statement.SecuritiesInfo:
            for sec_info in statement.SecuritiesInfo:
                # Only process stocks (STK) - ignore options, futures, cash, etc.
                # assetCategory is an enum (AssetClass.STOCK), not a string
                if not hasattr(sec_info, 'assetCategory') or sec_info.assetCategory != AssetClass.STOCK:
                    continue

                # Use conid as unique identifier
                conid = sec_info.conid if hasattr(sec_info, 'conid') else None
                if not conid:
                    continue

                securities[conid] = {
                    'conid': conid,
                    'isin': sec_info.isin if hasattr(sec_info, 'isin') else None,
                    'symbol': sec_info.symbol if hasattr(sec_info, 'symbol') else '',
                    'description': sec_info.description if hasattr(sec_info, 'description') else '',
                    'currency': sec_info.currency if hasattr(sec_info, 'currency') else 'USD',
                    'asset_category': 'STK',  # Only stocks
                    'exchange': sec_info.listingExchange if hasattr(sec_info, 'listingExchange') else None,
                }

        # Also check open positions for any securities not in SecuritiesInfo
        print(f"DEBUG: Checking OpenPositions - has attr: {hasattr(statement, 'OpenPositions')}")
        if hasattr(statement, 'OpenPositions'):
            print(f"DEBUG: OpenPositions value type: {type(statement.OpenPositions)}")
            print(f"DEBUG: OpenPositions truthy: {bool(statement.OpenPositions)}")
            if statement.OpenPositions:
                positions_list = list(statement.OpenPositions)
                print(f"DEBUG: Found {len(positions_list)} positions in OpenPositions")
                for position in statement.OpenPositions:
                    # Debug first position
                    if hasattr(position, 'symbol'):
                        print(f"DEBUG: Processing position - symbol: {position.symbol}, assetCategory: {getattr(position, 'assetCategory', 'N/A')}")

                    # Only process stocks - assetCategory is an enum (AssetClass.STOCK)
                    if not hasattr(position, 'assetCategory') or position.assetCategory != AssetClass.STOCK:
                        continue

                    conid = position.conid if hasattr(position, 'conid') else None
                    if not conid or conid in securities:
                        continue

                    securities[conid] = {
                        'conid': conid,
                        'isin': position.isin if hasattr(position, 'isin') else None,
                        'symbol': position.symbol if hasattr(position, 'symbol') else '',
                        'description': position.description if hasattr(position, 'description') else '',
                        'currency': position.currency if hasattr(position, 'currency') else 'USD',
                        'asset_category': 'STK',
                        'exchange': position.listingExchange if hasattr(position, 'listingExchange') else None,
                    }

        return list(securities.values())

    async def extract_taxlots(self, flex_data: Dict) -> List[Dict]:
        """
        Extract tax lot information from open positions.
        Tax lots represent individual purchases (with date, quantity, cost basis).
        Only includes stock positions - filters out other asset types.

        Args:
            flex_data: Parsed flex query data from fetch_flex_data()

        Returns:
            List of tax lot dictionaries with purchase details
        """
        statement = flex_data['statement']
        open_date_list = flex_data.get('open_date_times', [])  # Get manually extracted dates (list)
        taxlots = []

        # Extract from OpenPositions
        if hasattr(statement, 'OpenPositions') and statement.OpenPositions:
            positions_list = list(statement.OpenPositions)

            # Match by index - ibflex preserves order from XML
            for idx, position in enumerate(positions_list):
                # Only process stocks - assetCategory is an enum (AssetClass.STOCK)
                if not hasattr(position, 'assetCategory') or position.assetCategory != AssetClass.STOCK:
                    continue

                # Basic position info
                conid = position.conid if hasattr(position, 'conid') else None
                quantity = position.position if hasattr(position, 'position') else 0

                # Cost basis information
                cost_basis_money = position.costBasisMoney if hasattr(position, 'costBasisMoney') else 0
                cost_basis_price = position.costBasisPrice if hasattr(position, 'costBasisPrice') else 0

                # Get symbol for logging
                symbol = position.symbol if hasattr(position, 'symbol') else 'UNKNOWN'

                # Look up openDateTime from manually extracted list by index
                open_date = None
                if idx < len(open_date_list):
                    extracted = open_date_list[idx]
                    # Verify conid matches (safety check)
                    if extracted['conid'] == str(conid):
                        open_date = extracted['open_date']
                        print(f"Matched openDateTime for {symbol} (index {idx}): {open_date}")
                    else:
                        print(f"WARNING: Index mismatch at {idx}: expected conid {conid}, got {extracted['conid']}")

                if not open_date:
                    # Fallback to reportDate if openDateTime not found
                    report_date = position.reportDate if hasattr(position, 'reportDate') and position.reportDate else None
                    if report_date:
                        open_date = report_date if isinstance(report_date, date) else date.today()
                        print(f"WARNING: No openDateTime for {symbol} (index {idx}), using reportDate: {open_date}")
                    else:
                        open_date = date.today()
                        print(f"WARNING: No openDateTime or reportDate for {symbol} (conid: {conid}), using today's date")

                if not conid or quantity == 0:
                    continue

                taxlot = {
                    'conid': conid,
                    'open_date': open_date,
                    'quantity': Decimal(str(quantity)),
                    'cost_basis': Decimal(str(abs(cost_basis_money))),  # Total cost
                    'price_per_unit': Decimal(str(abs(cost_basis_price))),  # Price per share
                    'currency': position.currency if hasattr(position, 'currency') else 'USD',
                    'is_open': True,
                }

                taxlots.append(taxlot)

        return taxlots

    async def get_portfolio_summary(self) -> Dict:
        """
        Get a quick summary of the portfolio from IBKR.

        Returns:
            Dict with portfolio summary statistics
        """
        flex_data = await self.fetch_flex_data()
        securities = await self.extract_securities(flex_data)
        taxlots = await self.extract_taxlots(flex_data)

        return {
            'account_id': flex_data['account_id'],
            'from_date': flex_data['from_date'],
            'to_date': flex_data['to_date'],
            'securities_count': len(securities),
            'taxlots_count': len(taxlots),
            'total_positions': sum(lot['quantity'] for lot in taxlots),
        }
