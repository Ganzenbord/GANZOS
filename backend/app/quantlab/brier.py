"""De Brier-score en de betrouwbaarheidsanalyse (sectie 7).

Hiermee wordt de vraag "is dit model beter dan de regels" beantwoord met een getal in
plaats van met een gevoel.

De Brier-score is het gemiddelde kwadraat van de fout tussen de voorspelde kans en de
werkelijke uitkomst. Lager is beter; nul is perfect; 0,25 is wat je krijgt door altijd
"fiftyfifty" te zeggen.

Waarom niet simpelweg "hoe vaak had hij gelijk": dat straft een model dat eerlijk zegt "ik
weet het niet" even hard af als een model dat zelfverzekerd misgokt. En zelfverzekerd
misgokken is in traden precies wat je ruïneert.

De betrouwbaarheidsanalyse verdeelt de voorspellingen in bakjes en vergelijkt per bakje de
voorspelde kans met de werkelijke uitkomst. Dat is nodig omdat één getal kan verbergen dat
een model gemiddeld goed is en bij hoge kansen systematisch te optimistisch — en juist bij
hoge kansen zet je geld in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

SCALE = Decimal("0.0001")

# Een voorspelling met de uitkomst erbij: (kans tussen 0 en 1, is het gebeurd).
Decision = tuple[float, bool]


def brier_score(decisions: Sequence[Decision]) -> Decimal | None:
    """Het gemiddelde kwadraat van de fout. `None` als er niets te scoren is."""
    if not decisions:
        return None
    totaal = sum((kans - (1.0 if uitkomst else 0.0)) ** 2 for kans, uitkomst in decisions)
    return Decimal(str(totaal / len(decisions))).quantize(SCALE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReliabilityBin:
    low: Decimal
    high: Decimal
    count: int
    mean_predicted: float
    observed_rate: float

    @property
    def gap(self) -> Decimal:
        """Hoeveel de voorspelling naast de werkelijkheid zat, in dit bakje.

        Positief betekent te optimistisch: het model voorspelde een hogere kans dan er
        werkelijk uitkwam."""
        return Decimal(str(self.mean_predicted - self.observed_rate)).quantize(SCALE)


def reliability(decisions: Sequence[Decision], *, bins: int = 10) -> list[ReliabilityBin]:
    """Voorspelde kans tegen werkelijke uitkomst, per bakje.

    Lege bakjes blijven in de lijst staan: dat een model nooit een kans tussen 0,4 en 0,6
    geeft, is zelf een bevinding.
    """
    if bins <= 0:
        raise ValueError("Er moet minstens één bakje zijn.")
    breedte = Decimal(1) / Decimal(bins)
    uit: list[ReliabilityBin] = []
    for index in range(bins):
        laag = breedte * index
        hoog = breedte * (index + 1)
        # Het laatste bakje pakt de 1,0 mee; de rest is onder-, niet bovengrens-inclusief.
        inhoud = [
            (kans, uitkomst)
            for kans, uitkomst in decisions
            if float(laag) <= kans < float(hoog)
            or (index == bins - 1 and kans == 1.0)
        ]
        uit.append(
            ReliabilityBin(
                low=laag,
                high=hoog,
                count=len(inhoud),
                mean_predicted=(
                    sum(k for k, _ in inhoud) / len(inhoud) if inhoud else 0.0
                ),
                observed_rate=(
                    sum(1 for _, u in inhoud if u) / len(inhoud) if inhoud else 0.0
                ),
            )
        )
    return uit
