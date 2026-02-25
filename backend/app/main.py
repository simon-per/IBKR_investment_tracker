from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup: Initialize database
    await init_db()
    print("Database initialized successfully")

    # Initialize default ticker mappings
    from app.database import AsyncSessionLocal
    from app.repositories.ticker_mapping_repository import TickerMappingRepository

    async with AsyncSessionLocal() as db:
        try:
            mapping_repo = TickerMappingRepository(db)
            count = await mapping_repo.initialize_default_mappings()
            if count > 0:
                await db.commit()
                print(f"Initialized {count} default ticker mappings")
            else:
                print("Default ticker mappings already exist")
        except Exception as e:
            print(f"Warning: Could not initialize ticker mappings: {str(e)}")
            await db.rollback()

    # Start the scheduler for daily automatic syncs
    from app.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    scheduler.start()
    print("Scheduler started - Syncs at 08:00, 15:00, 22:00 Europe/Berlin")

    yield

    # Shutdown: Clean up resources
    print("Application shutting down")
    scheduler.shutdown()
    print("Scheduler shut down successfully")


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


# Health check endpoint
@app.get("/")
async def root():
    return {
        "message": "IBKR Portfolio Analyzer API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Import and include routers
from app.routers import sync, portfolio, market_data, analyst_ratings, allocation, scheduler

app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(market_data.router, prefix="/api/market-data", tags=["market-data"])
app.include_router(analyst_ratings.router, prefix="/api/analyst-ratings", tags=["analyst-ratings"])
app.include_router(allocation.router, prefix="/api/allocation", tags=["allocation"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["scheduler"])
# app.include_router(securities.router, prefix="/api/securities", tags=["securities"])
# app.include_router(taxlots.router, prefix="/api/taxlots", tags=["taxlots"])
