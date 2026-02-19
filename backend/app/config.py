from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# Get the project root directory (parent of backend folder)
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # IBKR Configuration
    ibkr_token: str
    ibkr_query_id: str

    # Alpha Vantage Configuration
    alpha_vantage_api_key: str = ""  # Optional for initial setup

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///./portfolio.db"

    # CORS Configuration (comma-separated string to avoid Pydantic JSON-parsing issues with List from env vars)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Logging
    log_level: str = "INFO"

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
