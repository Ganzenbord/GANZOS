"""Wat er binnenkomt bij het koppelen van een dienst.

Deze modellen gaan de andere kant op dan de rest: hier hóórt een sleutel in te staan. Wat
eruit komt is `IntegrationOut`, en daar staat hij niet in.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IntegrationIn(BaseModel):
    key: str = Field(
        min_length=1,
        max_length=64,
        description="Korte sleutel van de dienst, bijvoorbeeld 'higgsfield'",
    )
    name: str = Field(min_length=1, max_length=120, description="Hoe hij in het scherm heet")
    category: str | None = Field(default=None, max_length=64)
    credentials: dict[str, Any] | None = Field(
        default=None,
        description="Je eigen sleutels, bijvoorbeeld {\"api_key\": \"...\"}. Ze gaan "
        "versleuteld de database in en komen nooit terug in een antwoord.",
    )


class IntegrationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    credentials: dict[str, Any] | None = Field(
        default=None,
        description="Weglaten laat de bestaande sleutel staan; een leeg object gooit hem weg.",
    )


class CredentialFieldOut(BaseModel):
    """Eén in te vullen veld. `masked` bepaalt of het scherm hem als wachtwoord toont."""

    name: str
    label: str
    masked: bool
    hint: str | None = None


class CapabilityOut(BaseModel):
    """Eén functie en zijn sleutels.

    Hier staat met opzet geen enkele waarde in, alleen `missing_fields` met de namen van
    wat nog leeg is. Zien dat er iets mist mag; meelezen niet.
    """

    key: str
    name: str
    category: str
    purpose: str
    # "integration", "channel", "account" of "server".
    store: str
    where: str
    docs_url: str | None = None
    # Of er code is die deze sleutel echt gebruikt. False betekent: de plek staat klaar,
    # maar invullen doet nog niets.
    wired: bool
    note: str | None = None
    # "connected", "incomplete", "missing", "elsewhere" of "no_key_needed".
    state: str
    missing_fields: list[str]
    fields: list[CredentialFieldOut]
