"""Versleutelde opslag van provider-tokens.

Tokens van banken, exchanges en social-platforms staan versleuteld in de database.
Wie de database in handen krijgt, heeft daarmee nog geen toegang tot de accounts.
De sleutel komt uit GANZ_ENCRYPTION_KEY en staat nooit in de repository.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class TokenVault:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:  # pragma: no cover - opstartfout
            raise RuntimeError(
                "GANZ_ENCRYPTION_KEY is geen geldige Fernet-sleutel. "
                "Maak er een met: python -c \"from cryptography.fernet import Fernet; "
                'print(Fernet.generate_key().decode())"'
            ) from exc

    def encrypt(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        return self._fernet.encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")

    def decrypt(self, blob: str | None) -> dict[str, Any] | None:
        if not blob:
            return None
        try:
            return json.loads(self._fernet.decrypt(blob.encode("utf-8")).decode("utf-8"))
        except (InvalidToken, ValueError):
            # Een onleesbaar token betekent doorgaans dat de sleutel is gewisseld.
            # Dan is opnieuw koppelen de enige weg; laat Ganz daar niet op crashen.
            return None


_vault: TokenVault | None = None


def get_vault() -> TokenVault:
    global _vault
    if _vault is None:
        _vault = TokenVault(get_settings().encryption_key)
    return _vault
