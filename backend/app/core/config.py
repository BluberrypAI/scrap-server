from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "prod"] = "local"
    # Swagger UI (/docs) and OpenAPI schema. Turn off on public servers if needed.
    docs_enabled: bool = True

    # SQLite works with zero setup; use postgresql+asyncpg://... for Docker/Azure.
    database_url: str = "sqlite+aiosqlite:///./local.db"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Azure Database for PostgreSQL requires TLS: set DB_SSL=require there.
    db_ssl: Literal["disable", "require"] = "disable"

    jwt_secret: str = INSECURE_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    # Signs the short-lived session cookie Authlib uses for OAuth state/nonce.
    session_secret: str = INSECURE_SECRET

    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    cookie_domain: str | None = None
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "common"

    @model_validator(mode="after")
    def _reject_insecure_secrets_in_prod(self) -> "Settings":
        if self.app_env == "prod":
            if INSECURE_SECRET in (self.jwt_secret, self.session_secret):
                raise ValueError("JWT_SECRET and SESSION_SECRET must be set in prod")
            if not self.is_postgres:
                raise ValueError("DATABASE_URL must point to PostgreSQL in prod")
        if not self.cookie_domain:
            self.cookie_domain = None
        return self

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
