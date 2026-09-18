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
from app.core.permissions import PERMISSIONS, permissions_for_tier, tier_allows
from app.schemas.auth import (
    ConfirmationResponse,
    ConfirmRequest,
    LoginRequest,
    SetPinRequest,
    SetPinResponse,
    TokenResponse,
    UserOut,
)
from app.core.security import create_token, hash_password, verify_password
from app.models.confirmation import ConfirmationMethod
from app.services import confirmation_service
from app.utils.pin import InvalidPinError, validate_pin
from app.services.activity_service import log_activity

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    # Eén en dezelfde melding voor een onbekend e-mailadres en een fout wachtwoord,
    # zodat je niet kunt aftasten welke accounts bestaan.
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mailadres of wachtwoord klopt niet")
    await log_activity(
        session,
        action=ActivityAction.USER_LOGGED_IN,
        user_id=user.id,
        message=f"{user.display_name} is ingelogd.",
    )
    await session.commit()
    settings = get_settings()
    return TokenResponse(
        access_token=create_token(user.id, "access", origin="password"),
        expires_in_minutes=settings.access_token_minutes,
    )


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

    verzoek = await confirmation_service.create(
        session,
        user=user,
        method=methode,
        settings=settings,
        permission_key=payload.permission_key,
        origin=herkomst,
        origin_confidence=zekerheid,
    )
    try:
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


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=user.tier,
        permissions=permissions_for_tier(user.tier),
    )


@router.get("/permissions")
async def permission_registry(user: User = Depends(get_current_user)):
    """Het hele register, met per recht of deze gebruiker het heeft."""
    return [
        {
            "key": perm.key,
            "description": perm.description,
            "max_tier": perm.max_tier,
            "sensitive": perm.sensitive,
            "granted": tier_allows(user.tier, perm.key),
        }
        for perm in PERMISSIONS
    ]
