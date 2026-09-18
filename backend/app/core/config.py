"""Instellingen van Ganz.

Alles komt uit environment variables, zodat er nooit een sleutel in de repository
belandt. In productie weigert Ganz te starten zonder eigen sleutels: een
standaardsleutel zou betekenen dat versleutelde tokens door iedereen te lezen zijn.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

# Alleen in development mag Ganz terugvallen op vaste sleutels. De waarden zijn
# met opzet zichtbaar onzin, zodat ze nooit per ongeluk in productie blijven staan.
DEV_SECRET_KEY = "dev-only-not-secret-change-me"
DEV_ENCRYPTION_KEY = "ZGV2LW9ubHktbm90LXNlY3JldC1jaGFuZ2UtbWUtMDAwMDA="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="GANZ_", extra="ignore", case_sensitive=False
    )

    environment: Environment = "development"
    app_name: str = "Ganz"
    api_prefix: str = "/api"

    database_url: str = "postgresql+asyncpg://ganz:ganz@localhost:5432/ganz"

    # Ondertekent de inlogtokens.
    secret_key: str = DEV_SECRET_KEY
    access_token_minutes: int = 60 * 12
    # Een tweede bevestiging is kort geldig: hij dekt één gevoelige handeling af.
    confirmation_token_minutes: int = 5

    # Fernet-sleutel waarmee provider-tokens versleuteld in de database staan.
    encryption_key: str = DEV_ENCRYPTION_KEY

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Achtergrondsynchronisatie. Het dashboard leest alleen wat hier is opgehaald,
    # zodat een pagina-refresh nooit een provider aanroept.
    scheduler_enabled: bool = True
    finance_sync_minutes: int = 15
    social_sync_minutes: int = 30
    upload_check_minutes: int = 1

    # Ouder dan dit en het dashboard noemt de gegevens verouderd.
    stale_after_minutes: int = 60

    # Seed-data is uitsluitend voor development; zie scripts/seed.py.
    allow_seed_data: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def check_production_secrets(self) -> None:
        """Roept alarm als productie nog op de ontwikkelsleutels draait."""
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("GANZ_SECRET_KEY")
        if self.encryption_key == DEV_ENCRYPTION_KEY:
            problems.append("GANZ_ENCRYPTION_KEY")
        if self.allow_seed_data:
            problems.append("GANZ_ALLOW_SEED_DATA moet in productie uit staan")
        if problems:
            raise RuntimeError(
                "Ganz start niet: stel deze omgevingsvariabelen in voor productie: "
                + ", ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check_production_secrets()
    return settings
