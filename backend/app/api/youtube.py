"""Koppelen met YouTube, en zien of dat gelukt is."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_confirmation, require_permission
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.user import User
from app.schemas.youtube import YouTubeConnectOut, YouTubeStatusOut
from app.services import youtube_service

logger = logging.getLogger("ganz.youtube")

router = APIRouter(prefix="/youtube", tags=["youtube"])


@router.get("/status", response_model=YouTubeStatusOut)
async def youtube_status(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_permission("integrations.read")),
    settings: Settings = Depends(get_settings),
):
    """Staat de koppeling? En zo niet, wat ontbreekt er nog?"""
    return await youtube_service.status(session, user.id, settings)


@router.post("/connect", response_model=YouTubeConnectOut)
async def connect(
    user: User = Depends(require_confirmation("integrations.manage")),
    settings: Settings = Depends(get_settings),
):
    """Geeft het adres waar je bij Google toestemming geeft.

    Ganz stuurt je niet zelf door: de app opent de link in je eigen browser. Dat moet ook,
    want je logt daar in bij Google en dat hoort niet in een venster van Ganz te gebeuren.
    """
    try:
        return YouTubeConnectOut(authorization_url=youtube_service.start(user, settings))
    except youtube_service.YouTubeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Hier zet Google je neer nadat je toestemming hebt gegeven.

    Geen JSON maar een pagina: dit adres komt in de browser van de gebruiker terecht, niet in
    de app. Er staat één zin en verder niets — en zeker geen token.

    Let op: dit eindpunt heeft met opzet geen inlogcontrole. Google roept het aan, niet de
    app, dus er is geen Authorization-header. Wat hier de plaats van inneemt is de `state`:
    een door Ganz ondertekend token dat zegt van wie het verzoek kwam en dat na een kwartier
    vervalt. Zonder geldige state gebeurt er niets.
    """
    if error:
        # Google zet hier zijn eigen foutcode neer ("access_denied" als je op Annuleren
        # klikt). Die tonen we niet letterlijk; het is niet de taal van de gebruiker.
        return _pagina(
            "Geen toestemming gegeven",
            "Je hebt de koppeling afgebroken. Er is niets veranderd.",
            ok=False,
        )
    if not code or not state:
        return _pagina(
            "Onvolledige terugkoppeling",
            "Google gaf geen code terug. Probeer het opnieuw vanuit Ganz.",
            ok=False,
        )

    try:
        kanaal = await youtube_service.finish(
            session, code=code, state=state, settings=settings
        )
    except youtube_service.YouTubeError as exc:
        return _pagina("Koppelen lukte niet", exc.message, ok=False)

    await session.commit()
    return _pagina(
        "Gekoppeld",
        f"'{kanaal.channel_name}' hangt nu aan Ganz. Je kunt dit tabblad sluiten.",
        ok=True,
    )


@router.post("/disconnect")
async def disconnect(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_confirmation("integrations.manage")),
):
    """Maakt de koppeling los. De gemeten cijfers blijven staan."""
    losgemaakt = await youtube_service.disconnect(session, user.id)
    await session.commit()
    return {
        "disconnected": losgemaakt,
        "message": (
            "De koppeling is losgemaakt." if losgemaakt else "Er was niets om los te maken."
        ),
    }


def _pagina(titel: str, tekst: str, *, ok: bool) -> HTMLResponse:
    """Eén pagina voor alle afloopmogelijkheden; hij komt in een los tabblad terecht."""
    kleur = "#3fb950" if ok else "#e5484d"
    return HTMLResponse(
        f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titel} — Ganz</title>
<style>
 body {{ margin:0; min-height:100vh; display:grid; place-items:center;
        background:#080c14; color:#e6edf3;
        font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
 .kaart {{ max-width:420px; padding:28px 30px; border:1px solid #1d2b3d; border-radius:14px;
          background:#0d1420; }}
 h1 {{ margin:0 0 10px; font-size:19px; color:{kleur}; }}
 p {{ margin:0; font-size:14px; line-height:1.55; color:#9fb0c4; }}
</style></head>
<body><div class="kaart"><h1>{titel}</h1><p>{tekst}</p></div></body></html>""",
        status_code=200 if ok else 400,
    )
