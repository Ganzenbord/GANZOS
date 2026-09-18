"""Inloggen en bevestigen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.api.deps import get_current_user
from app.models.activity import ActivityAction
from app.models.user import User
from app.core.permissions import PERMISSIONS, permissions_for_tier
from app.schemas.auth import (
    ConfirmationResponse,
    ConfirmRequest,
    LoginRequest,
    TokenResponse,
    UserOut,
)
from app.core.security import create_token, verify_password
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
        access_token=create_token(user.id, "access"),
        expires_in_minutes=settings.access_token_minutes,
    )


@router.post("/confirm", response_model=ConfirmationResponse)
async def confirm(
    payload: ConfirmRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Geeft een kortlopend token voor één gevoelige handeling."""
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wachtwoord klopt niet")
    await log_activity(
        session,
        action=ActivityAction.USER_CONFIRMED,
        user_id=user.id,
        message="Tweede bevestiging gegeven.",
    )
    await session.commit()
    settings = get_settings()
    return ConfirmationResponse(
        confirmation_token=create_token(user.id, "confirmation"),
        expires_in_minutes=settings.confirmation_token_minutes,
    )


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
            "granted": user.tier <= perm.max_tier,
        }
        for perm in PERMISSIONS
    ]
