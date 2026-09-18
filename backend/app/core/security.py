"""Inloggen, wachtwoorden en tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# pbkdf2_sha256 is pure Python: geen losse bcrypt-versie die bij een upgrade breekt.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

TokenPurpose = Literal["access", "confirmation"]
# Waar een aanmelding vandaan komt. Een stem is na te maken, een wachtwoord niet zomaar.
TokenOrigin = Literal["password", "voice"]
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(
    subject: int,
    purpose: TokenPurpose = "access",
    **extra: Any,
) -> str:
    """Maak een token. `extra` komt er als losse velden bij te staan.

    Zo draagt een token dat uit een stemherkenning komt zijn herkomst met zich mee
    (`origin="voice"`, plus de gelijkenis). Dat is nodig omdat een stem na te maken is: bij
    gevoelige handelingen moet je kunnen zien waar de aanmelding vandaan kwam.
    """
    settings = get_settings()
    minutes = (
        settings.access_token_minutes
        if purpose == "access"
        else settings.confirmation_token_minutes
    )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "purpose": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        **{sleutel: waarde for sleutel, waarde in extra.items() if waarde is not None},
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, expected_purpose: TokenPurpose = "access") -> dict[str, Any] | None:
    """None bij een ongeldig, verlopen of verkeerd bedoeld token.

    Een inlogtoken mag nooit als tweede bevestiging gelden — anders is de bevestiging
    geen extra drempel maar een formaliteit.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != expected_purpose:
        return None
    return payload
