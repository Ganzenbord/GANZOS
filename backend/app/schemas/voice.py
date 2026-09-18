"""Wat /voice/... teruggeeft."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VoiceProfileOut(BaseModel):
    id: int
    user_id: int
    label: str
    embedding_model: str | None = Field(default=None, description="Het model dat deze afdruk maakte")
    embedding_dim: int | None = None
    sample_seconds: float | None = None
    enrolled_at: datetime | None = None
    active: bool


class EnrollResponse(BaseModel):
    success: bool = True
    profile_id: int
    profile: VoiceProfileOut
    message: str


class IdentifyResponse(BaseModel):
    result: Literal["identified", "unknown"]
    user_id: int | None = None
    display_name: str | None = None
    tier: int | None = Field(
        default=None, description="1 = volledige toegang, hoger = minder, leeg = geen toegang"
    )
    confidence: float = Field(
        description="Gelijkenis met de best passende stem, van -1 tot 1. Geen kansrekening: "
        "het is de hoek tussen twee vingerafdrukken."
    )
    threshold: float = Field(description="Vanaf deze waarde geldt een stem als herkend")
    runner_up_confidence: float | None = Field(
        default=None,
        description="Hoe dicht de op één na beste erbij zat. Ligt die vlakbij, dan is de "
        "uitslag minder stellig dan het cijfer suggereert.",
    )
    strong: bool = Field(
        default=False,
        description="Zeker genoeg voor gevoelige handelingen. Zo niet, dan kan er met dit "
        "token niets bevestigd worden en is het wachtwoord nodig.",
    )
    access_token: str | None = Field(
        default=None, description="Stuur mee als Authorization: Bearer <token>"
    )
    expires_in_minutes: int | None = None
    message: str
