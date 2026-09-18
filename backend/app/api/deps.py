"""FastAPI-afhankelijkheden: wie ben je, en mag je dit?"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.permissions import get_permission, tier_allows
from app.services import confirmation_service
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
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

    # Waar deze aanmelding vandaan komt, blijft het hele verzoek beschikbaar. /auth/confirm
    # heeft het nodig: een bevestiging die op een zwakke stemherkenning leunt, telt niet.
    request.state.token_origin = payload.get("origin")
    request.state.token_confidence = payload.get("confidence")
    return user


def require_permission(key: str) -> Callable[..., Awaitable[User]]:
    """Geeft een dependency die het recht `key` afdwingt.

    Dit is de gewone manier: een endpoint noemt alleen waar het over gaat, het register in
    `core/permissions.py` bepaalt welk niveau daarbij hoort. Geen if-jes per endpoint.
    """

    permission = get_permission(key)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.tier is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Je bent bekend, maar hebt geen toegang tot Ganz.",
            )
        if not tier_allows(user.tier, permission.key):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Hiervoor heb je tier {permission.max_tier} of hoger nodig "
                f"({permission.description.lower()}).",
            )
        return user

    return dependency


def require_tier(min_tier: int) -> Callable[..., Awaitable[User]]:
    """Eist rechtstreeks een tier, voor het enkele geval dat er geen passend recht bestaat.

    Let op de richting: een lager nummer is méér toegang, dus `min_tier` is de zwakste tier
    die nog naar binnen mag. Heeft wat je afschermt een naam, gebruik dan
    `require_permission()` — dan staat het in het register en zie je het terug in /auth/me.
    """

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.tier is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Je bent bekend, maar hebt geen toegang tot Ganz.",
            )
        if user.tier > min_tier:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Hiervoor heb je tier {min_tier} of hoger nodig.",
            )
        return user

    return dependency


async def consume_confirmation(
    request: Request,
    *,
    user: User,
    session: AsyncSession,
    permission_key: str,
    required: bool,
) -> bool:
    """Neem een meegestuurde bevestiging op, als die er is.

    Anders dan `require_confirmation` hangt dit niet aan een recht dat vooraf als gevoelig
    bekendstaat. Bij het uitvoeren van een skill blijkt pas uit de stappen of er iets
    gevoeligs bij zit — één skill haalt het weer op, de volgende publiceert een video.

    Geeft True als er bevestigd is, False als er niets is meegestuurd en het ook niet hoefde.
    Is er wél iets meegestuurd maar deugt het niet, dan is dat altijd een fout: stilzwijgend
    doorgaan zou betekenen dat een ongeldige bevestiging hetzelfde oplevert als geen.
    """
    kop = request.headers.get("X-Ganz-Confirmation")
    if not kop:
        if required:
            raise HTTPException(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "Deze skill doet iets onomkeerbaars. Bevestig eerst met je wachtwoord of "
                "pincode (POST /auth/confirm).",
            )
        return False

    payload = decode_token(kop, "confirmation")
    if payload is None or int(payload["sub"]) != user.id or "cr" not in payload:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED, "De bevestiging is ongeldig of verlopen."
        )
    try:
        await confirmation_service.consume(
            session,
            verzoek_id=int(payload["cr"]),
            user_id=user.id,
            permission_key=permission_key,
        )
    except confirmation_service.ConfirmationError as exc:
        await session.commit()
        raise HTTPException(exc.status_code, exc.message) from exc

    request.state.confirmed = True
    return True


def require_confirmation(key: str) -> Callable[..., Awaitable[User]]:
    """Als het recht gevoelig is, moet er ook een geldige bevestiging mee.

    Die haal je op met POST /auth/confirm en je wachtwoord of pincode. Zo kan een gestolen
    inlogtoken alleen kijken, niet je financiële accounts loskoppelen — en een herkende stem
    evenmin, want een stem is na te maken.

    Het token verwijst naar een rij in `confirmation_requests`. Die rij wordt hier opgebruikt:
    één bevestiging dekt één handeling af, en hetzelfde token kan niet nog een keer langs de
    kassa. Zonder die rij zou je achteraf ook niet kunnen zien dát er bevestigd is.
    """

    permission = get_permission(key)
    permission_dep = require_permission(key)

    async def dependency(
        request: Request,
        user: User = Depends(permission_dep),
        session: AsyncSession = Depends(get_session),
        x_ganz_confirmation: str | None = Header(default=None),
    ) -> User:
        if not permission.sensitive:
            return user

        payload = decode_token(x_ganz_confirmation or "", "confirmation")
        if payload is None or int(payload["sub"]) != user.id or "cr" not in payload:
            raise HTTPException(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "Bevestig eerst met je wachtwoord of pincode (POST /auth/confirm).",
            )

        try:
            await confirmation_service.consume(
                session,
                verzoek_id=int(payload["cr"]),
                user_id=user.id,
                permission_key=permission.key,
            )
        except confirmation_service.ConfirmationError as exc:
            # Commit wat de service aan de rij veranderde (bijvoorbeeld op 'failed' zetten),
            # anders verdwijnt dat spoor bij het terugdraaien.
            await session.commit()
            raise HTTPException(exc.status_code, exc.message) from exc
        await session.commit()

        request.state.confirmed = True
        return user

    return dependency
