"""FastAPI-afhankelijkheden: wie ben je, en mag je dit?"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.permissions import get_permission, tier_allows
from app.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Niet ingelogd")
    payload = decode_token(credentials.credentials, "access")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessie verlopen, log opnieuw in")
    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account bestaat niet of is geblokkeerd")
    return user


def require_permission(key: str) -> Callable[..., Awaitable[User]]:
    """Geeft een dependency die het recht `key` afdwingt."""

    permission = get_permission(key)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not tier_allows(user.tier, permission.key):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Hiervoor heb je tier {permission.max_tier} of hoger nodig "
                f"({permission.description.lower()}).",
            )
        return user

    return dependency


def require_confirmation(key: str) -> Callable[..., Awaitable[User]]:
    """Als het recht gevoelig is, moet er ook een geldig bevestigingstoken mee.

    Dat token haal je op met POST /auth/confirm en je wachtwoord. Zo kan een gestolen
    inlogtoken alleen kijken, niet je financiële accounts loskoppelen.
    """

    permission = get_permission(key)
    permission_dep = require_permission(key)

    async def dependency(
        request: Request,
        user: User = Depends(permission_dep),
        x_ganz_confirmation: str | None = Header(default=None),
    ) -> User:
        if not permission.sensitive:
            return user
        payload = decode_token(x_ganz_confirmation or "", "confirmation")
        if payload is None or int(payload["sub"]) != user.id:
            raise HTTPException(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "Bevestig eerst met je wachtwoord (POST /auth/confirm).",
            )
        request.state.confirmed = True
        return user

    return dependency
