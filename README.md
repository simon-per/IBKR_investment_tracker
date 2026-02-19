# IBKR Portfolio Analyzer

A comprehensive portfolio tracking application for Interactive Brokers accounts, focusing on securities and tax lots with dual-line chart visualization (cost basis vs. market value).

## Features

- 📊 **Dual-Line Portfolio Chart** - Track cost basis (invested) and market value (current worth) over time
- 💰 **Multi-Currency Support** - All values converted to EUR as base currency
- 🌍 **Multi-Exchange Tracking** - Same securities on different exchanges (e.g., Amazon on NASDAQ vs XETRA) tracked separately using ISIN codes
- 📈 **Real-Time Market Data** - Yahoo Finance integration for international stocks with exchange-specific pricing
- 💼 **Position Breakdown** - Detailed view of all holdings with gain/loss analysis
- 🔄 **IBKR Flex Query Integration** - Import your portfolio data directly from Interactive Brokers

## Tech Stack

### Backend
- **FastAPI** - Modern async Python web framework
- **SQLAlchemy 2.0** - Async ORM with SQLite database
- **Alembic** - Database migrations
- **ibflex** - IBKR Flex Query XML parsing
- **yfinance** - Market data (primary, free)
- **Alpha Vantage** - Market data (fallback, requires API key)
- **Frankfurter API** - Currency conversion (free, EUR-based)

### Frontend
- **React 18** + **TypeScript**
- **Vite** - Fast build tool
- **TanStack Query** - Data fetching and caching
- **Recharts** - Chart visualization
- **Tailwind CSS** - Styling
- **shadcn/ui** - UI components

## Architecture

```
┌─────────────────┐
│  IBKR Flex Query │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              Backend (FastAPI)                       │
├─────────────────────────────────────────────────────┤
│  • IBKRService: Parse Flex Query (STK only)         │
│  • SecurityRepository: ISIN + Exchange composite key │
│  • TaxLotRepository: Purchase tracking               │
│  • CurrencyService: Frankfurter API + caching        │
│  • MarketDataService: Yahoo Finance + caching        │
│  • PortfolioService: Cost basis & market value calc  │
└────────┬────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│            Frontend (React)                          │
├─────────────────────────────────────────────────────┤
│  • Dashboard: Main view with charts & cards          │
│  • PortfolioValueChart: Dual-line Recharts visual   │
│  • PortfolioSummaryCards: Metrics overview           │
│  • PositionsList: Holdings table with gain/loss      │
└─────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.12+
- Node.js 18+
- IBKR Flex Query configured (see setup below)
- (Optional) Alpha Vantage API key for US stocks fallback

## Installation

### 1. Clone and Setup Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head
```

### 2. Configure Environment Variables

Create `.env` file in the project root:

```env
# IBKR Configuration (REQUIRED)
IBKR_TOKEN=your_flex_query_token
IBKR_QUERY_ID=your_flex_query_id

# Alpha Vantage API (OPTIONAL - for US stocks fallback)
ALPHA_VANTAGE_API_KEY=your_api_key_here

# Database (default is SQLite)
DATABASE_URL=sqlite+aiosqlite:///./portfolio.db
```

### 3. Setup Frontend

```bash
cd frontend

# Install dependencies
npm install

# Build (optional, for production)
npm run build
```

## IBKR Flex Query Configuration

Configure your Interactive Brokers Flex Query with these fields:

### Open Positions Section
**Required Fields:**
- ✅ Currency
- ✅ Asset Class
- ✅ Symbol
- ✅ Quantity
- ✅ Cost Basis Price
- ✅ Cost Basis Money
- ✅ Open Date Time
- ✅ Description
- ✅ Listing Exchange
- ✅ Conid
- ✅ ISIN
- ✅ Report Date

### Filters
- **Asset Category**: Stocks (STK) only
- **Exclude**: Securities with non-standard currency codes (e.g., RUS)

### Format Settings
- **Format**: XML
- **Period**: Last Business Day (or your preferred range)
- **Date Format**: yyyyMMdd
- **Time Format**: HHmmss

## Running the Application

### Start Backend (Terminal 1)

```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Backend will be available at: `http://localhost:8000`
API docs at: `http://localhost:8000/docs`

### Start Frontend (Terminal 2)

```bash
cd frontend
npm run dev
```

Frontend will be available at: `http://localhost:5173`

## Usage

1. **Sync IBKR Data**
   - Click "Sync IBKR Data" button in the dashboard
   - This fetches your portfolio from Interactive Brokers
   - Securities and tax lots are stored in the database

2. **View Portfolio Value**
   - The dual-line chart shows:
     - **Purple line**: Cost Basis (total invested over time)
     - **Green line**: Market Value (current worth)
   - Automatically fetches market prices from Yahoo Finance

3. **Analyze Positions**
   - View all holdings in the positions table
   - See gain/loss for each security
   - Track holdings across different exchanges

## API Endpoints

### Portfolio
- `GET /api/portfolio/value-over-time` - Portfolio value timeline
- `GET /api/portfolio/summary` - Current portfolio summary
- `GET /api/portfolio/positions` - Detailed positions breakdown

### Sync
- `POST /api/sync/ibkr` - Sync data from IBKR Flex Query

## Database Schema

```sql
-- Securities: ISIN + Exchange composite key
CREATE TABLE securities (
    id INTEGER PRIMARY KEY,
    isin VARCHAR(12) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    description VARCHAR(200),
    currency VARCHAR(3) NOT NULL,
    conid INTEGER UNIQUE NOT NULL,
    exchange VARCHAR(20),
    UNIQUE(isin, exchange)
);

-- Tax Lots: Purchase tracking
CREATE TABLE taxlots (
    id INTEGER PRIMARY KEY,
    security_id INTEGER REFERENCES securities(id),
    open_date DATE NOT NULL,
    quantity NUMERIC(18,6) NOT NULL,
    cost_basis NUMERIC(18,6) NOT NULL,
    cost_basis_eur NUMERIC(18,6) NOT NULL,
    is_open BOOLEAN DEFAULT TRUE
);

-- Market Prices: Cached price data
CREATE TABLE market_prices (
    id INTEGER PRIMARY KEY,
    security_id INTEGER REFERENCES securities(id),
    date DATE NOT NULL,
    close_price NUMERIC(18,6) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    source VARCHAR(50) DEFAULT 'yahoo_finance',
    UNIQUE(security_id, date)
);

-- Exchange Rates: Cached currency conversions
CREATE TABLE exchange_rates (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    from_currency VARCHAR(3) NOT NULL,
    to_currency VARCHAR(3) NOT NULL,
    rate NUMERIC(18,8) NOT NULL,
    UNIQUE(date, from_currency, to_currency)
);
```

## Key Design Decisions

### ISIN + Exchange Tracking
The same stock traded on different exchanges (e.g., Amazon on NASDAQ in USD vs. XETRA in EUR) is tracked as **separate securities** because:
- Different trading prices
- Different currencies
- Different tax lot purchases

Example:
```python
# Amazon US
Security(isin="US0231351067", exchange="NASDAQ", symbol="AMZN", currency="USD")

# Amazon DE
Security(isin="US0231351067", exchange="XETRA", symbol="AMZ", currency="EUR")
```

### Market Data Sources
1. **Yahoo Finance** (Primary)
   - Free, no API key required
   - Excellent international coverage
   - Exchange-specific tickers (e.g., "AMZN", "AMZ.DE")

2. **Alpha Vantage** (Fallback)
   - Requires API key
   - Primarily US stocks
   - Used if Yahoo Finance fails

### Currency Conversion
- **Frankfurter API** for historical exchange rates
- All rates cached in database
- Base currency: EUR

## Project Structure

```
IBKR Investment Tracker/
├── backend/
│   ├── app/
│   │   ├── models/          # SQLAlchemy models
│   │   ├── repositories/    # Data access layer
│   │   ├── services/        # Business logic
│   │   ├── routers/         # API endpoints
│   │   ├── schemas/         # Pydantic models
│   │   ├── config.py        # Settings
│   │   ├── database.py      # DB setup
│   │   └── main.py          # FastAPI app
│   ├── alembic/             # Database migrations
│   ├── requirements.txt
│   └── portfolio.db         # SQLite database (generated)
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── lib/             # API client & utilities
│   │   ├── App.tsx          # Main app
│   │   └── main.tsx         # Entry point
│   ├── package.json
│   └── vite.config.ts
├── .env                     # Environment variables
└── README.md
```

## Troubleshooting

### Backend Issues

**"Unknown currency 'RUS'" error**
- Exclude Russian securities from your IBKR Flex Query
- Or update Flex Query to exclude non-standard currency codes

**"Alpha Vantage API key not configured"**
- Yahoo Finance will be used instead (recommended)
- Add `ALPHA_VANTAGE_API_KEY` to `.env` if you want US stocks fallback

**Database errors**
```bash
# Reset database
rm portfolio.db
alembic upgrade head
```

### Frontend Issues

**"Cannot connect to backend"**
- Ensure backend is running on port 8000
- Check `.env` file has `VITE_API_URL=http://localhost:8000`

**Build errors**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

## Future Enhancements

- [ ] Tax lot sale tracking (currently only tracks open positions)
- [ ] Dividend and cash transaction tracking
- [ ] Portfolio allocation pie chart
- [ ] Custom date range selector for charts
- [ ] Dark mode toggle
- [ ] Export to CSV/Excel
- [ ] Multi-portfolio support
- [ ] Performance attribution analysis

## License

Private project - Not licensed for distribution

## Support

For issues or questions, please check:
1. IBKR Flex Query configuration
2. Backend logs (`uvicorn` output)
3. Frontend console (browser DevTools)
4. Database integrity (`portfolio.db`)
