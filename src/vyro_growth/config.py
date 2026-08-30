from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Vyro Growth Engine"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://vyro:vyro@localhost:5432/vyro_growth"
    outbound_enabled: bool = Field(
        default=False,
        description="Global kill switch. Must be explicitly enabled before any outbound action.",
    )
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
