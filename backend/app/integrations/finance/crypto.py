"""Crypto-wallets waarderen op de actuele marktprijs.

De gebruiker vult in wát hij heeft (munt en aantal); de koers komt van CoinGecko.
Het saldo is dus echt en actueel, en er is geen API-sleutel of exchange-koppeling
voor nodig. Hoeveel er in de wallet zit, vult de gebruiker zelf in of leest een
latere wallet-provider uit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.integrations.base import Balance, ProviderError, ProviderNotConfigured

COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"


class CryptoPriceProvider:
    key = "crypto_price"
    display_name = "Crypto (marktprijs)"
    read_only = True

    def __init__(self, base_url: str = COINGECKO_PRICE_URL, timeout: float = 10.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        creds = credentials or {}
        return bool(creds.get("asset_id")) and creds.get("amount") is not None

    async def fetch_balance(self, credentials: dict[str, Any] | None) -> Balance:
        if not self.is_configured(credentials):
            raise ProviderNotConfigured(
                "Vul de munt (bijvoorbeeld 'bitcoin') en het aantal in."
            )
        assert credentials is not None
        asset_id = str(credentials["asset_id"]).lower()
        currency = str(credentials.get("currency", "EUR")).upper()
        try:
            amount = Decimal(str(credentials["amount"]))
        except (InvalidOperation, TypeError) as exc:
            raise ProviderNotConfigured("Het aantal is geen geldig getal.") from exc

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    self._base_url,
                    params={"ids": asset_id, "vs_currencies": currency.lower()},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Koers ophalen mislukt: {exc.__class__.__name__}") from exc

        price = (payload.get(asset_id) or {}).get(currency.lower())
        if price is None:
            raise ProviderError(f"Geen koers gevonden voor '{asset_id}' in {currency}.")
        try:
            value = amount * Decimal(str(price))
        except InvalidOperation as exc:
            raise ProviderError("De ontvangen koers is geen geldig getal.") from exc

        return Balance(
            value=value,
            currency=currency,
            external_account_id=asset_id,
            meta={"asset_id": asset_id, "unit_price": str(price)},
            measured_at=datetime.now(timezone.utc),
        )
