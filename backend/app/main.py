import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.auth import log_write_auth_state, write_auth_enabled, write_auth_middleware
from app.config import settings
from app.database import init_db
from app.observability import request_id_middleware, unhandled_exception_handler
from app.rate_limit import rate_limit_middleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup: Initialize database
    await init_db()
    logger.info("Database initialized successfully")

    # Initialize default ticker mappings
    from app.database import AsyncSessionLocal
    from app.repositories.ticker_mapping_repository import TickerMappingRepository

    async with AsyncSessionLocal() as db:
        try:
            mapping_repo = TickerMappingRepository(db)
            count = await mapping_repo.initialize_default_mappings()
            if count > 0:
                await db.commit()
                logger.info(f"Initialized {count} default ticker mappings")
            else:
                logger.info("Default ticker mappings already exist")
        except Exception as e:
            logger.info(f"Warning: Could not initialize ticker mappings: {str(e)}")
            await db.rollback()

    # Seed the default base (display) currency
    from app.repositories.app_settings_repository import AppSettingsRepository

    async with AsyncSessionLocal() as db:
        try:
            settings_repo = AppSettingsRepository(db)
            if await settings_repo.ensure_default_base_currency():
                await db.commit()
                logger.info("Seeded default base currency (EUR)")
        except Exception as e:
            logger.info(f"Warning: Could not seed base currency: {str(e)}")
            await db.rollback()

    # Say plainly whether the write API is protected. An unprotected one that nobody
    # notices is exactly the failure app/auth.py exists to prevent.
    log_write_auth_state()

    # Start the scheduler for daily automatic syncs.
    #
    # Gated because starting it is not a neutral act: the jobs reach the live
    # IBKR Flex token and Yahoo, so a developer running uvicorn locally would
    # arm real syncs against a rate-limited, lockout-prone API. Defaults to on,
    # so production keeps its schedule; local .env sets SCHEDULER_ENABLED=false.
    from app.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    if settings.scheduler_enabled:
        scheduler.start()
        logger.info("Scheduler started - Syncs at 08:00, 13:00, 15:00, 20:00, 22:00 Europe/Berlin")
    else:
        # Logged loudly: a silently disabled scheduler looks exactly like a
        # healthy site whose data has quietly stopped moving.
        logger.warning(
            "Scheduler DISABLED (SCHEDULER_ENABLED=false) - no automatic IBKR, "
            "FX, market-data or dividend syncs will run in this process"
        )

    yield

    # Shutdown: Clean up resources
    logger.info("Application shutting down")
    # Safe when the scheduler was never started — shutdown() no-ops on a None
    # scheduler, which is exactly the disabled case.
    scheduler.shutdown()


# Create FastAPI application
app = FastAPI(
    title="IBKR Portfolio Analyzer API",
    description="API for tracking and analyzing Interactive Brokers portfolio with cost basis and market value",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# `add_middleware` builds the stack outermost-LAST, so these run in reverse of the
# order written: request id first (every log line and every response, including the
# ones the layers below reject, carries it), then the rate limit (cheap, and it should
# shed load before any real work), then write auth.
app.middleware("http")(write_auth_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(request_id_middleware)

# Nothing escapes as an unlabelled 500 with a possibly-token-bearing message.
app.add_exception_handler(Exception, unhandled_exception_handler)


# Health check endpoint
@app.get("/")
async def root():
    return {
        "message": "IBKR Portfolio Analyzer API",
        "version": settings.app_version,
        "status": "running"
    }


@app.get("/health")
async def health_check(request: Request):
    """
    Liveness plus enough identity to answer "which build is live, and is it armed?"
    from a browser. Previously `{"status": "healthy"}` alone, so confirming a deploy
    had landed — or that the scheduler was actually running — needed ssh.

    Deliberately unauthenticated and un-throttled: the deploy script and any uptime
    check poll it, and it exposes no portfolio data.
    """
    return {
        "status": "healthy",
        "version": settings.app_version,
        "commit": settings.git_commit,
        "scheduler_enabled": settings.scheduler_enabled,
        "write_auth_enabled": write_auth_enabled(),
        "request_id": getattr(request.state, "request_id", None),
    }


# Import and include routers
from app.routers import sync, portfolio, market_data, analyst_ratings, allocation, scheduler, fundamentals, watchlist, dividends, tax, settings as settings_router

app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(market_data.router, prefix="/api/market-data", tags=["market-data"])
app.include_router(analyst_ratings.router, prefix="/api/analyst-ratings", tags=["analyst-ratings"])
app.include_router(allocation.router, prefix="/api/allocation", tags=["allocation"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["scheduler"])
app.include_router(fundamentals.router, prefix="/api/fundamentals", tags=["fundamentals"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(dividends.router, prefix="/api/dividends", tags=["dividends"])
app.include_router(tax.router, prefix="/api/tax", tags=["tax"])
# app.include_router(securities.router, prefix="/api/securities", tags=["securities"])
# app.include_router(taxlots.router, prefix="/api/taxlots", tags=["taxlots"])
