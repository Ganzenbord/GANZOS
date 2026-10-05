"""Een synthetische markt, om de datalaag te kunnen bouwen en bewijzen zonder netwerk.

**Dit is verzonnen data en dat mag nooit onduidelijk zijn.** De bron heet `synthetic`, elk
event draagt die naam, en het datakwaliteitsrapport meldt het aantal synthetische events
apart. Er mag geen enkel hypothese-resultaat op deze data worden gebaseerd; hij is er om de
machinerie te testen — de ketting, de replay, de controles — niet om iets over de markt te
zeggen.

De bron is deterministisch: dezelfde seed geeft dezelfde events, tot de laatste cent. Zonder
dat is er niets om een replay tegen af te meten.

Met `defects` maakt de bron met opzet slechte data. Dat is hoe je weet dat een controle
werkt: een controle die nooit iets vindt, is niet te onderscheiden van een controle die
stuk is.
"""

from __future__ import annotations

import json
import random
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.quantlab.feed import RawEvent

VENUE = "synthetic-dex"
CHAIN = "synthetic"


class SyntheticDefect(StrEnum):
    """Gebreken die de bron met opzet kan inbouwen."""

    GAP = "gap"
    ZERO_PRICE = "zero_price"
    NEGATIVE_PRICE = "negative_price"
    ROUNDED_PRICE = "rounded_price"
    OUT_OF_ORDER = "out_of_order"
    FUTURE_TIMESTAMP = "future_timestamp"
    DUPLICATE = "duplicate"
    BROKEN_JSON = "broken_json"


# Elk gebrek op zijn eigen tick, zodat ze samen in één opname kunnen zitten. Zouden ze
# allemaal op dezelfde tick landen, dan zou een onleesbaar event de andere verdringen en
# leek het alsof die controles niets vonden.
_DEFECT_STEP: dict[SyntheticDefect, int] = {
    SyntheticDefect.ZERO_PRICE: 3,
    SyntheticDefect.NEGATIVE_PRICE: 4,
    SyntheticDefect.ROUNDED_PRICE: 5,
    SyntheticDefect.OUT_OF_ORDER: 6,
    SyntheticDefect.FUTURE_TIMESTAMP: 7,
    SyntheticDefect.DUPLICATE: 8,
    SyntheticDefect.BROKEN_JSON: 9,
}


class SyntheticPoolSource:
    """Een paar pools die een uur lang prijzen afgeven.

    De prijsbeweging is een simpele random walk met een vaste seed. Hij doet niet alsof hij
    op een echte memecoin lijkt: dat zou de verkeerde suggestie wekken. Wat hij wel doet is
    genoeg events met genoeg variatie afgeven om de datalaag echt te belasten.
    """

    name = "synthetic"

    def __init__(
        self,
        *,
        seed: int,
        start_at: datetime,
        duration: timedelta,
        pools: int = 3,
        cadence_seconds: int = 10,
        defects: set[SyntheticDefect] | frozenset[SyntheticDefect] | None = None,
    ) -> None:
        self._seed = seed
        self._start_at = start_at
        self._duration = duration
        self._pools = pools
        self._cadence = cadence_seconds
        self._defects = frozenset(defects or ())

    def streams(self) -> tuple[str, ...]:
        return ("ticks",)

    def _gebrek(self, defect: SyntheticDefect, stap: int) -> bool:
        return defect in self._defects and stap == _DEFECT_STEP[defect]

    def _event(self, payload: dict[str, object], moment: datetime) -> RawEvent:
        # `separators` vast, zodat de tekst van een event niet afhangt van de Python-versie.
        tekst = json.dumps(payload, separators=(",", ":"), default=str)
        return RawEvent(
            source=self.name, stream="ticks", payload_raw=tekst, received_at=moment
        )

    async def events(self) -> AsyncIterator[RawEvent]:
        toeval = random.Random(self._seed)
        einde = self._start_at + self._duration

        pools = []
        for nummer in range(self._pools):
            pools.append(
                {
                    "pool": f"pool-{nummer + 1}",
                    "token": f"token-{nummer + 1}",
                    # De pools gaan niet allemaal op hetzelfde moment open; H1 kijkt naar
                    # tokenleeftijd, dus dat verschil moet erin zitten.
                    "created_at": self._start_at + timedelta(minutes=nummer * 3),
                    "price": Decimal(str(round(toeval.uniform(0.000001, 0.01), 12))),
                    "liquidity": Decimal(str(round(toeval.uniform(5_000, 80_000), 2))),
                }
            )

        for pool in pools:
            yield self._event(
                {
                    "type": "pool_created",
                    "pool": pool["pool"],
                    "token": pool["token"],
                    "venue": VENUE,
                    "chain": CHAIN,
                    "observed_at": pool["created_at"].isoformat(),
                    "pool_created_at": pool["created_at"].isoformat(),
                    "liquidity_usd": str(pool["liquidity"]),
                },
                pool["created_at"],
            )

        moment = self._start_at
        stap = 0
        while moment < einde:
            stap += 1
            for index, pool in enumerate(pools):
                if moment < pool["created_at"]:
                    continue

                # Een gat: tien minuten lang geen enkel event voor de eerste pool.
                if (
                    SyntheticDefect.GAP in self._defects
                    and index == 0
                    and self._start_at + timedelta(minutes=5)
                    <= moment
                    < self._start_at + timedelta(minutes=15)
                ):
                    continue

                beweging = Decimal(str(round(toeval.uniform(-0.04, 0.045), 6)))
                pool["price"] = max(
                    Decimal("0.000000000001"),
                    (pool["price"] * (Decimal("1") + beweging)).quantize(
                        Decimal("0.000000000001"), rounding=ROUND_HALF_UP
                    ),
                )
                prijs: Decimal | str = pool["price"]
                tijdstip = moment

                if index == 0:
                    if self._gebrek(SyntheticDefect.ZERO_PRICE, stap):
                        prijs = Decimal("0")
                    if self._gebrek(SyntheticDefect.NEGATIVE_PRICE, stap):
                        prijs = Decimal("-0.5")
                    if self._gebrek(SyntheticDefect.ROUNDED_PRICE, stap):
                        # Een prijs die ineens op twee decimalen staat terwijl deze pool
                        # rond de duizendste cent handelt: dat is een feed die afrondt.
                        prijs = Decimal("0.01")
                    if self._gebrek(SyntheticDefect.FUTURE_TIMESTAMP, stap):
                        tijdstip = moment + timedelta(minutes=30)
                    if self._gebrek(SyntheticDefect.OUT_OF_ORDER, stap):
                        tijdstip = moment - timedelta(minutes=2)

                if index == 0 and self._gebrek(SyntheticDefect.BROKEN_JSON, stap):
                    yield RawEvent(
                        source=self.name,
                        stream="ticks",
                        payload_raw='{"type":"tick","pool":"pool-1",',
                        received_at=moment,
                    )
                    continue

                payload = {
                    "type": "tick",
                    "pool": pool["pool"],
                    "token": pool["token"],
                    "venue": VENUE,
                    "chain": CHAIN,
                    "observed_at": tijdstip.isoformat(),
                    "pool_created_at": pool["created_at"].isoformat(),
                    "price_usd": str(prijs),
                    "liquidity_usd": str(pool["liquidity"]),
                    "volume_usd": str(
                        Decimal(str(round(toeval.uniform(10, 4_000), 2)))
                    ),
                    "volume_window_seconds": self._cadence,
                }
                event = self._event(payload, moment)
                yield event

                # Een dubbel event: exact dezelfde tekst nog een keer.
                if index == 0 and self._gebrek(SyntheticDefect.DUPLICATE, stap):
                    yield event

            moment += timedelta(seconds=self._cadence)
