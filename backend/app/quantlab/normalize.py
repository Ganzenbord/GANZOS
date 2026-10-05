"""Van ruwe tekst naar een tick waar de Screener mee kan werken.

De velden hieronder volgen niet uit een aanbieder maar uit hypothese H1 zelf. Die heeft
precies vier dingen nodig: de leeftijd van het token (`pool_created_at`), de prijs
(`price_usd`, voor de hoogste prijs van de eerste tien minuten), het volume per venster
(`volume_usd` met `volume_window_seconds`, voor "laatste 5 minuten versus de mediaan van de
eerste 10") en de liquiditeit (`liquidity_usd`, voor "minstens 50x de positiegrootte").

Zo blijft de laag venue-agnostisch: komt er een andere bron bij, dan hoeft alleen de
`Normalizer` van die bron geschreven te worden en verandert er niets aan de Screener.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.quantlab.feed import RawEvent, as_utc, parse_payload

# Dezelfde schalen als de kolommen in de database. Dit is geen detail: PostgreSQL geeft een
# Numeric(30,12) terug met twaalf decimalen, dus 1,5 komt terug als 1,500000000000. Zou de
# afdruk de tekst van het getal gebruiken zoals hij toevallig is, dan verschilt hij voor en
# na het opslaan — en dan lijkt een replay een ander resultaat te geven terwijl de data
# identiek is.
PRICE_SCALE = Decimal("0.000000000001")
MONEY_SCALE = Decimal("0.01")


class TickKind(StrEnum):
    POOL_CREATED = "pool_created"
    TICK = "tick"
    TRADE = "trade"


@dataclass(frozen=True)
class MarketTick:
    kind: TickKind
    venue: str
    chain: str
    pool_address: str
    token_address: str
    observed_at: datetime
    price_usd: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_usd: Decimal | None = None
    volume_window_seconds: int | None = None
    pool_created_at: datetime | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "venue": self.venue,
            "chain": self.chain,
            "pool_address": self.pool_address,
            "token_address": self.token_address,
            "observed_at": self.observed_at,
            "price_usd": self.price_usd,
            "liquidity_usd": self.liquidity_usd,
            "volume_usd": self.volume_usd,
            "volume_window_seconds": self.volume_window_seconds,
            "pool_created_at": self.pool_created_at,
        }


@runtime_checkable
class Normalizer(Protocol):
    """Zet één ruw event om in nul of meer ticks. Mag nooit terugschrijven naar de ruwe
    opslag: die is de waarheid en blijft zoals hij is."""

    def normalize(self, event: RawEvent) -> Sequence[MarketTick]: ...


def _schaal(waarde: object, schaal: Decimal) -> str:
    """Een getal in de afdruk, altijd op dezelfde schaal. Leeg blijft leeg."""
    if waarde is None:
        return ""
    return str(Decimal(str(waarde)).quantize(schaal, rounding=ROUND_HALF_UP))


def tick_digest(ticks: Iterable[Mapping[str, Any] | MarketTick]) -> str:
    """Eén afdruk over een hele reeks ticks.

    Dit is waarmee "identiek resultaat" wordt vastgesteld. Met het oog vergelijken van
    duizend rijen doet niemand twee keer; een afdruk vergelijk je wel elke run.
    """
    hasher = hashlib.sha256()
    for tick in ticks:
        rij = tick.as_row() if isinstance(tick, MarketTick) else dict(tick)
        kind = rij.get("kind")
        velden = (
            str(getattr(kind, "value", kind) or ""),
            str(rij.get("venue") or ""),
            str(rij.get("chain") or ""),
            str(rij.get("pool_address") or ""),
            str(rij.get("token_address") or ""),
            as_utc(rij["observed_at"]).isoformat() if rij.get("observed_at") else "",
            _schaal(rij.get("price_usd"), PRICE_SCALE),
            _schaal(rij.get("liquidity_usd"), MONEY_SCALE),
            _schaal(rij.get("volume_usd"), MONEY_SCALE),
            "" if rij.get("volume_window_seconds") is None else str(rij["volume_window_seconds"]),
            as_utc(rij["pool_created_at"]).isoformat() if rij.get("pool_created_at") else "",
        )
        hasher.update(("|".join(velden) + "\n").encode("utf-8"))
    return hasher.hexdigest()


class JsonTickNormalizer:
    """De normalizer voor bronnen die al een tick-achtig JSON-object sturen.

    Dit is de vorm die de synthetische bron gebruikt en die een eigen opname kan volgen.
    Een echte aanbieder stuurt iets anders; daarvoor komt er een eigen normalizer naast
    deze, zonder dat hier iets verandert.
    """

    def normalize(self, event: RawEvent) -> Sequence[MarketTick]:
        payload = parse_payload(event.payload_raw)
        soort = str(payload.get("type") or "")
        if soort not in {k.value for k in TickKind}:
            # Geen tick (bijvoorbeeld een hartslag van de feed). Niets om te normaliseren,
            # en dat is geen fout: het ruwe event blijft staan.
            return ()
        ontbreekt = [veld for veld in ("pool", "observed_at") if not payload.get(veld)]
        if ontbreekt:
            raise ValueError(f"Event mist {', '.join(ontbreekt)}")
        return (
            MarketTick(
                kind=TickKind(soort),
                venue=str(payload.get("venue") or event.source),
                chain=str(payload.get("chain") or ""),
                pool_address=str(payload["pool"]),
                token_address=str(payload.get("token") or ""),
                observed_at=as_utc(payload["observed_at"]),
                price_usd=_decimaal(payload.get("price_usd")),
                liquidity_usd=_decimaal(payload.get("liquidity_usd")),
                volume_usd=_decimaal(payload.get("volume_usd")),
                volume_window_seconds=(
                    int(payload["volume_window_seconds"])
                    if payload.get("volume_window_seconds") is not None
                    else None
                ),
                pool_created_at=(
                    as_utc(payload["pool_created_at"])
                    if payload.get("pool_created_at")
                    else None
                ),
            ),
        )


def _decimaal(waarde: object) -> Decimal | None:
    if waarde is None or waarde == "":
        return None
    return Decimal(str(waarde))


# Welke normalizer bij welke bron hoort. Een bron zonder normalizer wordt wél opgeslagen
# maar niet omgezet: de ruwe data is dan veilig en het omzetten kan later alsnog.
NORMALIZERS: dict[str, Normalizer] = {"synthetic": JsonTickNormalizer()}

DEFAULT_NORMALIZER: Normalizer = JsonTickNormalizer()


def normalizer_for(source: str) -> Normalizer:
    return NORMALIZERS.get(source, DEFAULT_NORMALIZER)
