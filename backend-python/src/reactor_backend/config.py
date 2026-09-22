from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-only settings for the Python migration service."""

    model_config = SettingsConfigDict(
        env_prefix="REACTOR_PY_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "reactor-backend-python"
    environment: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8200
    log_level: str = "INFO"

    database_url: SecretStr | None = Field(default=None, repr=False)
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "ai-agent-station"
    mysql_user: str = "reactor"
    mysql_password: SecretStr = Field(default=SecretStr(""), repr=False)
    mysql_pool_size: int = Field(default=10, ge=1, le=128)
    mysql_max_overflow: int = Field(default=20, ge=0, le=256)
    mysql_pool_recycle_seconds: int = Field(default=1800, ge=30)
    database_ready_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password.get_secret_value())
        database = quote_plus(self.mysql_database)
        return (
            f"mysql+asyncmy://{user}:{password}@{self.mysql_host}:{self.mysql_port}/"
            f"{database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
