"""Wisselkoersen naar euro.

Standaard via Frankfurter (de dagkoersen van de Europese Centrale Bank, gratis en
zonder sleutel). Lukt het ophalen niet, dan komt er géén koers terug — een account in
vreemde valuta telt dan zichtbaar niet mee, in plaats van mee te tellen op een
gegokte koers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
# De ECB publiceert één keer per werkdag. Vaker ophalen levert niets op en belast
# de dienst onnodig.
CACHE_TTL = timedelta(hours=6)


class FxRates:
    def __init__(self, base_url: str = FRANKFURTER_URL, timeout: float = 10.0) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._cache: dict[str, tuple[Decimal, datetime]] = {}
        self._lock = asyncio.Lock()

    async def rate_to_eur(self, currency: str) -> Decimal | None:
        currency = currency.upper()
        if currency == "EUR":
            return Decimal(1)

        now = datetime.now(timezone.utc)
        cached = self._cache.get(currency)
        if cached and now - cached[1] < CACHE_TTL:
            return cached[0]

        async with self._lock:
            # Een tweede wachter hoeft niet nog eens te bellen.
            cached = self._cache.get(currency)
            if cached and now - cached[1] < CACHE_TTL:
                return cached[0]
            rate = await self._fetch(currency)
            if rate is not None:
                self._cache[currency] = (rate, now)
            return rate

    async def _fetch(self, currency: str) -> Decimal | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    self._base_url, params={"from": currency, "to": "EUR"}
                )
                response.raise_for_status()
                payload = response.json()
            value = payload.get("rates", {}).get("EUR")
            if value is None:
                return None
            return Decimal(str(value))
        except (httpx.HTTPError, ValueError, KeyError, InvalidOperation):
            return None


_rates: FxRates | None = None


def get_fx_rates() -> FxRates:
    global _rates
    if _rates is None:
        _rates = FxRates()
    return _rates
