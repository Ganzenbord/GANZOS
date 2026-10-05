"""Wat er uit een databron komt, en hoe het onveranderd blijft (sectie 11).

Eén regel draagt dit hele bestand: **de ruwe opslag bewaart tekst, geen betekenis.** Wat de
bron stuurt gaat letter voor letter de database in, en de hash gaat over die letters. Zou
het event eerst geparsed en opnieuw opgeschreven worden, dan is "bit-voor-bit herhaalbaar"
een woord zonder inhoud: `{"a":1,"b":2}` en `{"b": 2, "a": 1}` betekenen hetzelfde, maar het
zijn niet dezelfde bytes, en een feed die morgen zijn sleutelvolgorde wijzigt zou stil een
ander corpus opleveren.

De ketting (`chain_step`) is er om te zien dát iemand in de data heeft gezeten. Elke rij
hangt aan de vorige; verander er één, en alles erna sluit niet meer aan.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RawEvent:
    """Eén event zoals het binnenkwam.

    `payload_raw` is de tekst, onaangeroerd. `received_at` is onze klok; de klok van de bron
    zit in de tekst en wordt bij het normaliseren eruit gehaald. Die twee apart houden is
    wat het later mogelijk maakt om feedvertraging te meten.
    """

    source: str
    stream: str
    payload_raw: str
    received_at: datetime


@runtime_checkable
class FeedSource(Protocol):
    """Een databron. Levert events en weet hoe hij heet; verder niets."""

    name: str

    def streams(self) -> tuple[str, ...]: ...

    def events(self) -> AsyncIterator[RawEvent]: ...


def canonical_hash(payload_raw: str) -> str:
    """De afdruk van de tekst zoals hij is. Geen sort_keys, geen herformattering."""
    return hashlib.sha256(payload_raw.encode("utf-8")).hexdigest()


def chain_step(previous_chain_hash: str | None, payload_hash: str) -> str:
    """De volgende schakel: de vorige schakel plus de afdruk van dit event."""
    basis = f"{previous_chain_hash or ''}:{payload_hash}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def parse_payload(payload_raw: str) -> dict[str, Any]:
    """JSON lezen zonder door een float te gaan.

    Een prijs van 0,000000123456 die door een float gaat, komt er niet hetzelfde uit — en
    bij memecoins zijn dat precies de prijzen. `parse_float=Decimal` houdt het exact. Een
    onleesbaar event geeft hier een `ValueError`; die wordt geteld, niet gerepareerd.
    """
    waarde = json.loads(payload_raw, parse_float=Decimal, parse_int=int)
    if not isinstance(waarde, dict):
        raise ValueError("Een event hoort een JSON-object te zijn.")
    return waarde


def as_utc(waarde: Any) -> datetime:
    """Een tijdstip uit een event, altijd met tijdzone. Zonder zone: UTC aannemen."""
    if isinstance(waarde, datetime):
        moment = waarde
    else:
        moment = datetime.fromisoformat(str(waarde).replace("Z", "+00:00"))
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(
        timezone.utc
    )


class JsonlFileSource:
    """Een bron die een opgenomen bestand teruggeeft, één event per regel.

    Hiermee kun je een corpus van buiten binnenhalen (een opname van iemand anders, of een
    export van een feed) zonder dat de rest van het lab weet dat het van schijf komt.
    """

    def __init__(self, path: str | Path, *, source: str, stream: str = "ticks") -> None:
        self.name = source
        self._path = Path(path)
        self._stream = stream

    def streams(self) -> tuple[str, ...]:
        return (self._stream,)

    async def events(self) -> AsyncIterator[RawEvent]:
        with self._path.open(encoding="utf-8") as bestand:
            for regel in bestand:
                tekst = regel.rstrip("\n")
                if not tekst.strip():
                    continue
                # De ontvangsttijd van een opname is de tijd in het event zelf: anders zou
                # elke replay een andere feedvertraging laten zien.
                try:
                    moment = as_utc(parse_payload(tekst).get("observed_at"))
                except Exception:
                    moment = datetime.now(timezone.utc)
                yield RawEvent(
                    source=self.name,
                    stream=self._stream,
                    payload_raw=tekst,
                    received_at=moment,
                )
