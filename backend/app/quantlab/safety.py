"""De veiligheidsfilters, en wat er gebeurt als je ze niet kunt verifiëren (sectie 8 en 10).

De filters uit H1 — LP burned of gelockt, mint- en freeze-authority afgeschaft, top-10
holders onder 20%, technisch geverifieerd verkoopbaar — houden het systeem in leven en zijn
geen edge. Ze hebben alle vier gegevens nodig die uit de chain komen, en die zijn er nog
niet: de netwerkpolicy laat geen bron door (zie het fase 2-rapport).

De regel uit de opdracht is daar duidelijk over: **wat niet te verifiëren is, wordt
uitgesloten en geteld.** Niet "waarschijnlijk wel goed". Dit bestand maakt dat expliciet met
drie uitkomsten in plaats van twee: goed, afgewezen, of niet te verifiëren.

`SyntheticSafetyOracle` geeft verzonnen uitslagen en zegt dat ook in zijn uitleg. Hij is er
om het pad te kunnen draaien en te kunnen tellen, niet om iets over een token te zeggen.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# De filters waar chaingegevens voor nodig zijn. Zolang die er niet zijn, zijn dit precies
# de dingen die "niet te verifiëren" opleveren.
CHAIN_FILTERS = (
    "lp_burned_or_locked",
    "mint_authority_revoked",
    "freeze_authority_revoked",
    "top10_holder_share",
    "sellability",
)


class SafetyStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class SafetyVerdict:
    status: SafetyStatus
    explanation: str
    failed_filters: tuple[str, ...] = field(default_factory=tuple)
    unverifiable_filters: tuple[str, ...] = field(default_factory=tuple)
    # `None` betekent met opzet "niet vast te stellen" en niet "nee". Dat verschil moet
    # zichtbaar blijven, want het is het verschil tussen een afgewezen token en een token
    # waar we niets over weten.
    sellable: bool | None = None


@runtime_checkable
class SafetyOracle(Protocol):
    name: str

    def check(self, pool_address: str) -> SafetyVerdict: ...


class AlwaysSafeOracle:
    """Alles goed. Alleen voor tests waarin veiligheid niet het onderwerp is.

    Met opzet een eigen klasse en geen vlag op het echte orakel: zo staat er in elke test
    die hem gebruikt zwart op wit dat de veiligheidsfilters daar niet worden getest.
    """

    name = "always_safe"

    def check(self, pool_address: str) -> SafetyVerdict:
        return SafetyVerdict(
            status=SafetyStatus.OK,
            explanation="Testorakel: alles goedgekeurd zonder iets te controleren.",
            sellable=True,
        )


class NeverVerifiableOracle:
    """Niets te verifiëren — de stand van zaken zolang er geen chaindata is.

    Dit is niet alleen een testdubbel: het is wat er werkelijk gebeurt als het lab vandaag
    zou draaien. Elk signaal wordt uitgesloten en geteld, en dat is het juiste gedrag.
    """

    name = "never_verifiable"

    def check(self, pool_address: str) -> SafetyVerdict:
        return SafetyVerdict(
            status=SafetyStatus.UNVERIFIABLE,
            explanation=(
                "Er is geen chaindata bereikbaar, dus LP-lock, authorities, holders en "
                "verkoopbaarheid zijn niet te verifiëren. Uitgesloten en geteld."
            ),
            unverifiable_filters=CHAIN_FILTERS,
            sellable=None,
        )


class SyntheticSafetyOracle:
    """Verzonnen uitslagen, reproduceerbaar per pool.

    Alleen om de drie paden te kunnen draaien en te kunnen tellen. De uitslag hangt aan de
    naam van de pool en aan het zaad, dus dezelfde pool krijgt altijd dezelfde uitslag —
    anders zou een token halverwege een run van veilig naar onveilig springen.
    """

    name = "synthetic"

    def __init__(
        self, *, seed: int, ok_share: float = 0.6, unverifiable_share: float = 0.2
    ) -> None:
        self._seed = seed
        self._ok = ok_share
        self._unverifiable = unverifiable_share

    def _fractie(self, pool_address: str) -> float:
        afdruk = hashlib.sha256(f"{self._seed}:{pool_address}".encode()).digest()
        return int.from_bytes(afdruk[:8], "big") / float(1 << 64)

    def check(self, pool_address: str) -> SafetyVerdict:
        waarde = self._fractie(pool_address)
        basis = "Synthetisch orakel: deze uitslag is verzonnen en zegt niets over een token."
        if waarde < self._ok:
            return SafetyVerdict(status=SafetyStatus.OK, explanation=basis, sellable=True)
        if waarde < self._ok + self._unverifiable:
            return SafetyVerdict(
                status=SafetyStatus.UNVERIFIABLE,
                explanation=f"{basis} Verkoopbaarheid niet vast te stellen.",
                unverifiable_filters=("sellability",),
                sellable=None,
            )
        return SafetyVerdict(
            status=SafetyStatus.FAILED,
            explanation=f"{basis} Afgewezen op de houdersverdeling.",
            failed_filters=("top10_holder_share",),
            sellable=True,
        )
