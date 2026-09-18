"""Wat de Ganz-modules teruggeven.

Elk model is een lijst van toegestane velden, niet een afdruk van een databaserij. Dat
verschil is het hele punt: komt er morgen een kolom bij met een sleutel erin, dan lekt hij
niet mee omdat hij hier niet genoemd staat.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PermissionOut(BaseModel):
    """Eén recht uit het register, met wat deze gebruiker ermee kan."""

    key: str
    description: str
    max_tier: int
    sensitive: bool
    granted: bool
    # None = deze gebruiker volgt gewoon zijn tier. True of False = er is een uitzondering.
    override: bool | None = None


class TimeOut(BaseModel):
    server_time: datetime
    timezone: str


class ConversationOut(BaseModel):
    id: int
    title: str
    last_message_at: datetime | None = None
    created_at: datetime


class IntegrationOut(BaseModel):
    """Een gekoppelde dienst.

    Let op wat er níét in staat: `credentials_encrypted`. Niet omdat het vergeten is maar
    omdat dit model bepaalt wat de client krijgt, en die kolom hoort daar nooit bij — ook
    niet versleuteld.
    """

    id: int
    key: str
    name: str
    category: str | None = None
    status: str
    status_detail: str | None = None
    last_checked_at: datetime | None = None
    # Of er gegevens zijn ingevuld. Alleen óf, nooit welke.
    has_credentials: bool = False


class WorkflowOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    enabled: bool
    trigger: str | None = None
    run_count: int
    last_run_at: datetime | None = None


class ProviderOut(BaseModel):
    """Een partij waar Ganz mee kan koppelen. Alleen de naamkaart, geen sleutels."""

    key: str | None = None
    platform: str | None = None
    display_name: str


class StatsPointOut(BaseModel):
    measured_at: datetime
    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    posts: int | None = None


class ChannelHistoryOut(BaseModel):
    channel_id: int
    platform: str
    channel_name: str
    points: list[StatsPointOut]


class MessageOut(BaseModel):
    """Voor eindpunten die alleen 'gelukt' hoeven te zeggen."""

    message: str


class DisconnectOut(BaseModel):
    disconnected: bool
    message: str
