"""Wat de YouTube-eindpunten teruggeven."""

from __future__ import annotations

from pydantic import BaseModel


class YouTubeStatusOut(BaseModel):
    """De stand van de koppeling. Geen enkel token zit hierin — met opzet."""

    configured: bool
    connected: bool
    can_upload: bool
    channel_name: str | None = None
    channel_id: str | None = None
    channel_status: str | None = None
    upload_privacy: str
    video_dir: str | None = None
    redirect_uri: str
    explanation: str


class YouTubeConnectOut(BaseModel):
    authorization_url: str
