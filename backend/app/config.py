from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# Get the backend directory (parent of app/)
# In Docker: /app/app/config.py → /app/.env
# Locally: backend/app/config.py → backend/.env
BACKEND_ROOT = Path(__file__).parent.parent
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    # IBKR Configuration
    ibkr_token: str
    ibkr_query_id: str

    # Alpha Vantage Configuration
    alpha_vantage_api_key: str = ""  # Optional for initial setup

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///./portfolio.db"

    # CORS Configuration (comma-separated string to avoid Pydantic JSON-parsing issues with List from env vars)
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"

    # Logging
    log_level: str = "INFO"

    # Whether to arm the APScheduler jobs on startup. Defaults to True so
    # production is unaffected; set SCHEDULER_ENABLED=false for local runs.
    # Without it, merely starting uvicorn on a dev machine arms the 08:00/13:00/
    # 15:00/20:00/22:00 Europe/Berlin jobs against the real IBKR token in .env
    # and against Yahoo — the two things this project must never do casually
    # (see the two rules at the top of CLAUDE.md).
    scheduler_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    @property
    def cors_origins_list(self) -> list:
        return [origin.strip() for origin in self.cors_origins.split(",")]


# Create a global settings instance
settings = Settings()
