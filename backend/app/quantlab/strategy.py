"""De `Strategy`-laag: wie wil er instappen, en waarom.

H2 is een gereserveerd slot in de opdracht, en deze interface moet het kunnen toevoegen
zonder refactor. Vandaar dat een strategie precies één ding doet: op een moment, gegeven de
kandidaten van dat moment, zeggen of hij er een wil. Wat er daarna gebeurt — de
veiligheidsfilters, de risicolaag, het fill-model — is niet aan de strategie.

`RandomEntryStrategy` is H0, de controlegroep. Hij stapt willekeurig in uit hetzelfde
universum als H1, met dezelfde exits en dezelfde kosten. Dat is de ruisvloer: elke strategie
levert winsten op, en de vraag is of ze meer opleveren dan willekeur.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Candidate:
    """Eén pool op één moment, zoals de datalaag hem geeft."""

    pool_address: str
    token_address: str
    venue: str
    chain: str
    observed_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    volume_usd: Decimal | None
    pool_created_at: datetime | None

    def age_minutes(self, moment: datetime) -> float | None:
        if self.pool_created_at is None:
            return None
        return (moment - self.pool_created_at).total_seconds() / 60


@runtime_checkable
class Strategy(Protocol):
    name: str

    def propose(
        self,
        *,
        moment: datetime,
        candidates: Sequence[Candidate],
        step_seconds: float,
    ) -> Candidate | None: ...


class RandomEntryStrategy:
    """H0: willekeurig instappen uit hetzelfde universum.

    De kans per tijdstap is zo gezet dat er over een uur ongeveer `attempts_per_hour`
    pogingen uitkomen. "Ongeveer", want het is kans; exact zou betekenen dat de instappen
    op een klok lopen en dat is geen willekeur meer.

    Het toeval komt uit een eigen generator met een eigen zaad, los van het fill-model. Dat
    is wat een stresstest geldig maakt: bij hetzelfde zaad probeert H0 exact dezelfde
    instappen, en is het enige verschil tussen de varianten het fill-model.
    """

    name = "random_entry"

    def __init__(
        self,
        *,
        seed: int,
        attempts_per_hour: float,
        min_age_minutes: float,
        max_age_minutes: float,
    ) -> None:
        self._random = random.Random(seed)
        self._per_hour = attempts_per_hour
        self._min_age = min_age_minutes
        self._max_age = max_age_minutes

    def eligible(self, moment: datetime, candidates: Sequence[Candidate]) -> list[Candidate]:
        uit = []
        for kandidaat in candidates:
            if kandidaat.price_usd is None or kandidaat.price_usd <= 0:
                continue
            leeftijd = kandidaat.age_minutes(moment)
            if leeftijd is None or not (self._min_age <= leeftijd <= self._max_age):
                continue
            uit.append(kandidaat)
        return uit

    def propose(
        self,
        *,
        moment: datetime,
        candidates: Sequence[Candidate],
        step_seconds: float,
    ) -> Candidate | None:
        kans = min(1.0, self._per_hour * max(step_seconds, 0.0) / 3600.0)
        # Altijd eerst trekken, ook als er niets in aanmerking komt. Zou de trekking van de
        # kandidaten afhangen, dan loopt de reeks toevalsgetallen uiteen tussen twee runs
        # over hetzelfde corpus, en is reproduceerbaarheid weg.
        gooi = self._random.random()
        kiezer = self._random.random()

        mogelijk = self.eligible(moment, candidates)
        if not mogelijk or gooi >= kans:
            return None
        return mogelijk[int(kiezer * len(mogelijk)) % len(mogelijk)]


class ScoredEntryStrategy:
    """Instappen op een score die al is uitgerekend (sectie 6).

    Let op wat deze klasse **niet** doet: hij roept geen model aan. Hij krijgt een kant en
    klare tabel van pool naar score mee, en past daar een drempel op toe. Dat is geen
    omslachtigheid maar de kern van de architectuur — sectie 6 zegt dat het entry-besluit
    alleen reeds opgeslagen scores en deterministische regels gebruikt.

    De scores worden in een aparte ronde gemaakt (`quant_scoring_service`), die wél een
    model mag aanroepen. Daardoor blijft het pad waarin een trade tot stand komt vrij van
    alles wat kan wachten, kan falen, of kan antwoorden met iets anders dan afgesproken.
    Er is een test die de hele importboom naloopt om dat vast te houden.
    """

    name = "scored_entry"

    def __init__(
        self,
        *,
        scores: Mapping[str, float],
        threshold: float,
        min_age_minutes: float,
        max_age_minutes: float,
        default_score: float | None = None,
    ) -> None:
        self._scores = scores
        self._threshold = threshold
        self._min_age = min_age_minutes
        self._max_age = max_age_minutes
        # Een pool zonder score doet standaard niet mee. Hem een score geven zou betekenen
        # dat een ontbrekende meting stilzwijgend een mening wordt.
        self._default = default_score

    def propose(
        self,
        *,
        moment: datetime,
        candidates: Sequence[Candidate],
        step_seconds: float,
    ) -> Candidate | None:
        beste: Candidate | None = None
        beste_score = self._threshold
        for kandidaat in candidates:
            if kandidaat.price_usd is None or kandidaat.price_usd <= 0:
                continue
            leeftijd = kandidaat.age_minutes(moment)
            if leeftijd is None or not (self._min_age <= leeftijd <= self._max_age):
                continue
            score = self._scores.get(kandidaat.pool_address, self._default)
            if score is None or score < self._threshold:
                continue
            if beste is None or score > beste_score:
                beste, beste_score = kandidaat, score
        return beste
