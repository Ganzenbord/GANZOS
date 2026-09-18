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
# Een Fernet-sleutel is precies 32 bytes, url-safe base64. De vorige waarde was er 35 en
# dus onbruikbaar: alles wat tokens versleutelt liep in development stuk op een 500, met
# een melding die naar de verkeerde kant wees. De tests merkten dat niet, want die zetten
# een eigen sleutel.
DEV_ENCRYPTION_KEY = "ZGV2LW9ubHktbm90LXNlY3JldC1jaGFuZ2UtbWUtMDA="


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
    # Mispogingen tellen over álle bevestigingen samen, niet per poging apart. Elke poging
    # is namelijk een nieuw verzoek, dus een grens per verzoek houdt niemand tegen die een
    # pincode van vier cijfers zit door te proberen.
    confirmation_max_failures: int = 5
    confirmation_lockout_minutes: int = 15

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

    # --- Stemherkenning -----------------------------------------------------
    # Het model dat van een opname een vingerafdruk maakt. Wissel je van model, dan moet
    # iedereen opnieuw worden ingeschreven: afdrukken van twee modellen zijn onvergelijkbaar.
    voice_model: str = "speechbrain/spkrec-ecapa-voxceleb"
    voice_model_cache_dir: str | None = None

    # Vanaf hoeveel gelijkenis (0 tot 1) een stem als herkend geldt. Hoger is strenger: vaker
    # "ik herken je niet", minder kans dat iemand anders wordt binnengelaten. 0.25 is de
    # waarde die SpeechBrain zelf aanhoudt — stel hem bij met echte opnames.
    voice_match_threshold: float = 0.25

    # Onder deze grens is de herkenning te zwak om iets mee te doen dat er toe doet. Zo'n
    # aanmelding krijgt wel een token, maar de bevestiging voor gevoelige acties kan er niet
    # mee (zie app/services/confirmation_service.py).
    voice_strong_threshold: float = 0.45

    voice_min_seconds: float = 1.0
    voice_max_seconds: float = 30.0
    voice_max_upload_bytes: int = 10 * 1024 * 1024

    # Zolang er nog geen enkele stem is ingeschreven kan niemand herkend worden, en zou
    # niemand ooit kunnen beginnen. Zet dit op false zodra iedereen erin staat.
    voice_enrollment_open_when_empty: bool = True

    # --- Skills -------------------------------------------------------------
    # Het model dat opdrachten en skills op betekenis vergelijkt. Draait lokaal; er gaat
    # nooit iets naar een externe dienst om te matchen.
    skill_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    skill_model_cache_dir: str | None = None

    # Vanaf hoeveel gelijkenis een skill bij een opdracht hoort. Te laag en Ganz pakt de
    # verkeerde skill; te hoog en hij zegt steeds dat hij het niet kan. Deze waarde geldt
    # voor beide manieren van matchen, en die tellen niet hetzelfde — zie docs/skills.md.
    skill_match_threshold: float = 0.45

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
