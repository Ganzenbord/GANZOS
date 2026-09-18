"""Inloggen en bevestigen."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.api.deps import get_current_user
from app.models.activity import ActivityAction
from app.models.user import User
from app.core.permissions import PERMISSIONS, allows, effective_permissions
from app.schemas.platform import PermissionOut
from app.schemas.auth import (
    ConfirmationResponse,
    ConfirmRequest,
    LoginRequest,
    ChangePasswordRequest,
    ChangePasswordResponse,
    RefreshRequest,
    RevokeResponse,
    SessionOut,
    SetPinRequest,
    SetPinResponse,
    TokenResponse,
    UserOut,
)
from app.core.security import create_token, hash_password, verify_password
from app.models.confirmation import ConfirmationMethod
from app.services import confirmation_service, session_service
from app.utils.pin import InvalidPinError, validate_pin
from app.services.activity_service import log_activity

router = APIRouter(prefix="/auth", tags=["auth"])


def _herkomst(request: Request) -> tuple[str | None, str | None]:
    """Vanaf welk apparaat komt dit verzoek?

    Achter een reverse proxy klopt `request.client` alleen als uvicorn met
    `--proxy-headers --forwarded-allow-ips` draait. Dat hoort in de opstartregel en niet
    hier: een header zelf uitlezen betekent hem geloven, en die kan iedereen verzinnen.
    Zie docs/server.md.
    """
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)
):
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    # Eén en dezelfde melding voor een onbekend e-mailadres en een fout wachtwoord,
    # zodat je niet kunt aftasten welke accounts bestaan.
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mailadres of wachtwoord klopt niet")

    settings = get_settings()
    ip, agent = _herkomst(request)
    sessie, vernieuwtoken = await session_service.create(
        session,
        user=user,
        settings=settings,
        device_name=payload.device_name,
        user_agent=agent,
        ip_address=ip,
    )
    await log_activity(
        session,
        action=ActivityAction.USER_LOGGED_IN,
        user_id=user.id,
        message=f"{user.display_name} is ingelogd op {payload.device_name or 'een apparaat'}.",
        subject_type="user_session",
        subject_id=sessie.id,
    )
    await session.commit()
    return TokenResponse(
        access_token=create_token(user.id, "access", origin="password", sid=sessie.id),
        expires_in_minutes=settings.access_token_minutes,
        refresh_token=vernieuwtoken,
        session_id=sessie.id,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, request: Request, session: AsyncSession = Depends(get_session)
):
    """Wisselt een vernieuwingstoken om voor een nieuw inlogtoken.

    Geen inlogcontrole nodig en ook niet mogelijk: het hele punt is dat het oude inlogtoken
    verlopen is. Het vernieuwingstoken is het bewijs, en het wordt bij elk gebruik vervangen.
    """
    settings = get_settings()
    ip, _ = _herkomst(request)
    try:
        sessie, gebruiker, nieuw = await session_service.rotate(
            session, token=payload.refresh_token, settings=settings, ip_address=ip
        )
    except session_service.SessionError as exc:
        if exc.code == "hergebruikt":
            await log_activity(
                session,
                action=ActivityAction.SESSION_REUSE_DETECTED,
                message="Een al vervangen vernieuwingstoken werd opnieuw aangeboden.",
            )
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc

    await session.commit()
    return TokenResponse(
        access_token=create_token(gebruiker.id, "access", origin="password", sid=sessie.id),
        expires_in_minutes=settings.access_token_minutes,
        refresh_token=nieuw,
        session_id=sessie.id,
    )


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Welke apparaten op dit moment toegang hebben."""
    huidige = getattr(request.state, "session_id", None)
    return [
        SessionOut(
            id=rij.id,
            device_name=rij.device_name,
            user_agent=rij.user_agent,
            ip_address=rij.ip_address,
            created_at=rij.created_at,
            last_used_at=rij.last_used_at,
            expires_at=rij.expires_at,
            current=rij.id == huidige,
        )
        for rij in await session_service.list_for(session, user.id)
    ]


@router.delete("/sessions/{session_id}", response_model=RevokeResponse)
async def revoke_session(
    session_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Gooit één apparaat eruit. Hiervoor is met opzet geen tweede bevestiging nodig.

    Wie zijn telefoon kwijt is, moet dat kunnen doen op het moment dat hij het merkt — niet
    na het opzoeken van een pincode. Het ergste dat een ander ermee kan is jou uitloggen.
    """
    gelukt = await session_service.revoke(session, user_id=user.id, session_id=session_id)
    if gelukt:
        await log_activity(
            session,
            action=ActivityAction.SESSION_REVOKED,
            user_id=user.id,
            message="Een apparaat is uitgelogd.",
            subject_type="user_session",
            subject_id=session_id,
        )
    await session.commit()
    return RevokeResponse(
        revoked=1 if gelukt else 0,
        message="Dit apparaat is uitgelogd." if gelukt else "Dit apparaat was al weg.",
    )


@router.post("/logout", response_model=RevokeResponse)
async def logout(
    request: Request,
    alles: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Logt dit apparaat uit, of met `?alles=true` allemaal.

    `alles=true` is wat je doet als je vermoedt dat er iets mis is: één knop en elk apparaat
    moet opnieuw inloggen, dit apparaat inbegrepen.
    """
    huidige = getattr(request.state, "session_id", None)
    if alles:
        aantal = await session_service.revoke_all(session, user_id=user.id)
        bericht = f"{aantal} apparaat(en) uitgelogd."
    elif huidige is not None:
        aantal = int(await session_service.revoke(session, user_id=user.id, session_id=huidige))
        bericht = "Uitgelogd." if aantal else "Deze sessie was al weg."
    else:
        aantal, bericht = 0, "Dit token hoort niet bij een sessie."
    if aantal:
        await log_activity(
            session,
            action=ActivityAction.USER_LOGGED_OUT,
            user_id=user.id,
            message=bericht,
        )
    await session.commit()
    return RevokeResponse(revoked=aantal, message=bericht)


@router.post("/confirm", response_model=ConfirmationResponse)
async def confirm(
    payload: ConfirmRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Geeft een kortlopende bevestiging voor één gevoelige handeling.

    De bevestiging staat als rij in de database; het token verwijst ernaar. Daardoor is
    achteraf te zien dát er bevestigd is en waarvoor, en kan dezelfde bevestiging niet twee
    keer gebruikt worden.
    """
    settings = get_settings()
    methode = ConfirmationMethod.PIN if payload.pin else ConfirmationMethod.PASSWORD

    # Kwam de aanmelding uit een stemherkenning, dan telt dat mee: een te zwakke herkenning
    # mag geen gevoelige handeling afdekken, hoe goed de pincode daarna ook is.
    herkomst = getattr(request.state, "token_origin", None)
    zekerheid = getattr(request.state, "token_confidence", None)

    try:
        verzoek = await confirmation_service.create(
            session,
            user=user,
            method=methode,
            settings=settings,
            permission_key=payload.permission_key,
            origin=herkomst,
            origin_confidence=zekerheid,
        )
        await confirmation_service.verify(
            session,
            verzoek=verzoek,
            user=user,
            secret=payload.pin or payload.password or "",
            settings=settings,
        )
    except confirmation_service.ConfirmationError as exc:
        await session.commit()  # de mislukte poging blijft staan, dat is het punt
        raise HTTPException(exc.status_code, exc.message) from exc

    await log_activity(
        session,
        action=ActivityAction.USER_CONFIRMED,
        user_id=user.id,
        message=f"Tweede bevestiging gegeven met {methode.value}.",
        context={"permission_key": payload.permission_key},
    )
    await session.commit()
    return ConfirmationResponse(
        confirmation_token=create_token(user.id, "confirmation", cr=verzoek.id),
        expires_in_minutes=settings.confirmation_token_minutes,
        confirmation_id=verzoek.id,
    )


@router.post("/pin", response_model=SetPinResponse)
async def set_pin(
    payload: SetPinRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Stel een pincode in of wijzig hem. Je huidige wachtwoord is nodig.

    Een pincode van vier cijfers is maar tienduizend mogelijkheden. Wat dat tegenhoudt is
    niet de code zelf maar het aantal pogingen per bevestiging (drie) — plus dat je hem
    alleen kunt gebruiken als je al ingelogd of herkend bent.
    """
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wachtwoord klopt niet")
    try:
        schoon = validate_pin(payload.pin)
    except InvalidPinError as exc:
        raise HTTPException(422, str(exc)) from exc

    user.pin_hash = hash_password(schoon)
    user.pin_updated_at = datetime.now(timezone.utc)
    await log_activity(
        session,
        action=ActivityAction.USER_PIN_SET,
        user_id=user.id,
        message="Pincode ingesteld.",
    )
    await session.commit()
    return SetPinResponse(message="Pincode ingesteld.")


@router.post("/password", response_model=ChangePasswordResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Wijzig je eigen wachtwoord, vanaf welk apparaat dan ook.

    Twee dingen die hier bij elkaar horen:

    - **Je huidige wachtwoord is nodig**, ook al ben je al ingelogd. Anders is een
      openstaande laptop genoeg om je account over te nemen.
    - **Alle andere apparaten worden uitgelogd.** Dat is precies waarom je je wachtwoord
      wijzigt als je vermoedt dat iemand meekijkt — en zonder deze regel doet het wijzigen
      niets aan de sessies die al open staan. Dit apparaat blijft ingelogd; anders zou je
      jezelf eruit gooien op het moment dat je het probleem aan het oplossen bent.
    """
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Je huidige wachtwoord klopt niet")
    if payload.new_password == payload.current_password:
        raise HTTPException(422, "Het nieuwe wachtwoord is hetzelfde als het oude.")

    user.password_hash = hash_password(payload.new_password)
    huidige = getattr(request.state, "session_id", None)
    aantal = await session_service.revoke_all(session, user_id=user.id, behalve=huidige)
    await log_activity(
        session,
        action=ActivityAction.USER_PASSWORD_CHANGED,
        user_id=user.id,
        message=f"Wachtwoord gewijzigd; {aantal} ander(e) apparaat(en) uitgelogd.",
    )
    await session.commit()
    return ChangePasswordResponse(
        message=(
            "Je wachtwoord is gewijzigd."
            + (f" {aantal} ander(e) apparaat(en) moeten opnieuw inloggen." if aantal else "")
        ),
        revoked_sessions=aantal,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=user.tier,
        permissions=effective_permissions(user.tier, user.overrides),
        has_pin=user.pin_hash is not None,
    )


@router.get("/permissions", response_model=list[PermissionOut])
async def permission_registry(user: User = Depends(get_current_user)):
    """Het hele register, met per recht of deze gebruiker het heeft."""
    return [
        {
            "key": perm.key,
            "description": perm.description,
            "max_tier": perm.max_tier,
            "sensitive": perm.sensitive,
            "granted": allows(user.tier, perm.key, user.overrides),
            # Of dit recht van zijn tier komt of apart is toegekend of ingetrokken. Zonder
            # dit onderscheid is een uitzondering onzichtbaar en dus niet te controleren.
            "override": user.overrides.get(perm.key),
        }
        for perm in PERMISSIONS
    ]
