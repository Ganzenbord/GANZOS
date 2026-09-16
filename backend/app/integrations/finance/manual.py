"""Handmatig bijgehouden rekening.

Niet elke bank heeft een API die je als particulier mag gebruiken. Dan vult de
gebruiker het bedrag zelf in. Dat is echte data — hij komt alleen niet automatisch
binnen, en het dashboard laat daarom eerlijk zien wanneer hij voor het laatst is
bijgewerkt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.base import Balance, ProviderNotConfigured


class ManualFinanceProvider:
    key = "manual"
    display_name = "Handmatig bijgehouden"
    read_only = True

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        return bool(credentials) and "value" in (credentials or {})

    async def fetch_balance(self, credentials: dict[str, Any] | None) -> Balance:
        if not self.is_configured(credentials):
            raise ProviderNotConfigured("Vul zelf een bedrag in bij dit account.")
        assert credentials is not None
        try:
            value = Decimal(str(credentials["value"]))
        except (InvalidOperation, TypeError) as exc:
            raise ProviderNotConfigured("Het ingevulde bedrag is geen geldig getal.") from exc
        return Balance(
            value=value,
            currency=str(credentials.get("currency", "EUR")).upper(),
            measured_at=datetime.now(timezone.utc),
        )
