"""Datakwaliteit (sectie 11): gaten, dubbele events, afgeronde prijzen, nulprijzen.

"Datakwaliteit eerst" betekent in de praktijk dit: een corpus met gaten en afgeronde
prijzen levert een backtest op die er prachtig uitziet en niets betekent. De controles
hieronder zijn pure functies over een reeks ticks, zodat ze zonder database te testen zijn
en in een replay dezelfde uitkomst geven als bij het opnemen.

Elke bevinding heeft een aantal, een paar voorbeelden en een uitleg in gewone taal. Het
aantal is er zodat je kunt zien of het erger wordt, de voorbeelden zodat je het kunt
nazoeken, en de uitleg omdat het rapport ook gelezen wordt door iemand die geen
programmeur is.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

# Een gat is pas een gat als het ruim boven de normale afstand tussen twee events ligt.
# Drie keer de mediaan: bij een feed die elke tien seconden stuurt, meldt hij vanaf een
# halve minuut stilte. Lager en elke hikje is een alarm.
GAP_FACTOR = Decimal("3")
GAP_MINIMUM = timedelta(seconds=30)

# Verschil tussen de klok van de bron en onze klok. Meer dan dit en de feed loopt achter.
STALE_SECONDS = 60

# Een tijdstip in de toekomst kan nooit; een paar seconden klokverschil wel.
FUTURE_TOLERANCE_SECONDS = 5

# Vanaf hoeveel bevindingen een controle een alarm wordt in plaats van een waarschuwing.
ALARM_SHARE = Decimal("0.01")


class DataCheck(StrEnum):
    GAP = "gap"
    DUPLICATE = "duplicate"
    ZERO_OR_NEGATIVE_PRICE = "zero_or_negative_price"
    ROUNDED_PRICE = "rounded_price"
    OUT_OF_ORDER = "out_of_order"
    FUTURE_TIMESTAMP = "future_timestamp"
    STALE_FEED = "stale_feed"
    PARSE_FAILURE = "parse_failure"


CHECK_UITLEG: dict[DataCheck, str] = {
    DataCheck.GAP: (
        "Er zit een gat in de data: tussen twee events zat veel meer tijd dan normaal. "
        "In dat gat kan de prijs alles hebben gedaan, dus elk resultaat dat eroverheen "
        "rekent, is niet te vertrouwen."
    ),
    DataCheck.DUPLICATE: (
        "Hetzelfde event kwam twee keer binnen. Beide staan in de ruwe opslag — die is "
        "append-only — maar als je ze meetelt, lijkt het volume hoger dan het was."
    ),
    DataCheck.ZERO_OR_NEGATIVE_PRICE: (
        "Een prijs van nul of lager bestaat niet. Dit is een fout van de bron of een pool "
        "die leeg is getrokken; in beide gevallen hoort er niet op gehandeld te worden."
    ),
    DataCheck.ROUNDED_PRICE: (
        "De prijs is afgerond op een paar decimalen terwijl deze pool veel kleinere "
        "getallen gebruikt. Een afgeronde prijs maakt een uitbraak zichtbaar die er niet "
        "was, of verbergt er een."
    ),
    DataCheck.OUT_OF_ORDER: (
        "Een event had een tijdstip dat vóór het vorige lag. Bij een trigger die naar 'de "
        "hoogste prijs van de eerste tien minuten' kijkt, verschuift dat de uitkomst."
    ),
    DataCheck.FUTURE_TIMESTAMP: (
        "Een event had een tijdstip in de toekomst. Dat betekent dat de klok van de bron "
        "of van deze machine niet goed staat, en tijd is hier de enige ordening die we "
        "hebben."
    ),
    DataCheck.STALE_FEED: (
        "De events kwamen veel later binnen dan het tijdstip dat erin staat. Voor "
        "onderzoek is dat te overzien, voor een trigger op een token van tien minuten oud "
        "niet."
    ),
    DataCheck.PARSE_FAILURE: (
        "Een event was niet te lezen als JSON. Het staat onveranderd in de ruwe opslag en "
        "is niet gerepareerd; er is alleen geen tick van gemaakt."
    ),
}


class QualityVerdict(StrEnum):
    NO_DATA = "no_data"
    OK = "ok"
    WARNING = "warning"
    ALARM = "alarm"


VERDICT_UITLEG: dict[QualityVerdict, str] = {
    QualityVerdict.NO_DATA: "Er is nog geen data opgenomen.",
    QualityVerdict.OK: "De opgenomen data ziet er schoon uit.",
    QualityVerdict.WARNING: "Er zijn kleine gebreken gevonden; de data is bruikbaar.",
    QualityVerdict.ALARM: (
        "Er zijn gebreken die een resultaat onbetrouwbaar maken. Eerst oplossen, dan "
        "conclusies."
    ),
}


@dataclass(frozen=True)
class Finding:
    check: DataCheck
    count: int
    severity: QualityVerdict
    explanation: str
    examples: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DataQualityReport:
    verdict: QualityVerdict
    explanation: str
    ticks: int
    raw_events: int
    pools: int
    synthetic_events: int
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    findings: tuple[Finding, ...]

    def count_of(self, check: DataCheck) -> int:
        for bevinding in self.findings:
            if bevinding.check is check:
                return bevinding.count
        return 0


def _ernst(aantal: int, totaal: int, *, altijd_alarm: bool = False) -> QualityVerdict:
    """Een los gebrek is een waarschuwing, een patroon is een alarm.

    Behalve bij prijzen die niet kunnen bestaan: één nulprijs is al genoeg om de data van
    die pool niet te vertrouwen.
    """
    if aantal <= 0:
        return QualityVerdict.OK
    if altijd_alarm:
        return QualityVerdict.ALARM
    if totaal > 0 and Decimal(aantal) / Decimal(totaal) >= ALARM_SHARE:
        return QualityVerdict.ALARM
    return QualityVerdict.WARNING


def quality_report(
    *,
    ticks: Sequence[Mapping[str, Any]],
    raw_count: int,
    duplicates: int,
    parse_failures: int,
    synthetic_events: int,
    now: datetime,
) -> DataQualityReport:
    """Het rapport over een reeks ticks.

    `ticks` komt in **aankomstvolgorde** binnen, niet chronologisch gesorteerd. Dat is geen
    detail: de controle op volgorde kijkt juist of een event een tijdstip had dat vóór zijn
    voorganger lag, en die bevinding verdwijnt als je de reeks eerst sorteert. De
    gatcontrole sorteert zelf wel, want een gat is een vraag over de klok.
    """
    if not ticks and raw_count == 0:
        return DataQualityReport(
            verdict=QualityVerdict.NO_DATA,
            explanation=VERDICT_UITLEG[QualityVerdict.NO_DATA],
            ticks=0,
            raw_events=0,
            pools=0,
            synthetic_events=0,
            first_observed_at=None,
            last_observed_at=None,
            findings=(),
        )

    per_pool: dict[str, list[Mapping[str, Any]]] = {}
    for tick in ticks:
        per_pool.setdefault(str(tick.get("pool_address") or ""), []).append(tick)

    gaten: list[str] = []
    nulprijzen: list[str] = []
    afgerond: list[str] = []
    verkeerde_volgorde: list[str] = []
    toekomst: list[str] = []
    traag: list[str] = []

    for pool, reeks in per_pool.items():
        # Volgorde: in de reeks zoals hij binnenkwam.
        aankomst = [tick["observed_at"] for tick in reeks]
        for i in range(1, len(aankomst)):
            if (aankomst[i] - aankomst[i - 1]).total_seconds() < 0:
                verkeerde_volgorde.append(f"{pool}@{aankomst[i].isoformat()}")

        # Gaten: in de reeks op de klok. Een event dat te laat binnenkwam, laat op de klok
        # wél een gat achter, en dat is precies wat je wil weten.
        tijden = sorted(aankomst)
        afstanden = [
            (tijden[i] - tijden[i - 1]).total_seconds()
            for i in range(1, len(tijden))
            if (tijden[i] - tijden[i - 1]).total_seconds() > 0
        ]
        normaal = Decimal(str(statistics.median(afstanden))) if afstanden else Decimal("0")
        grens = max(float(normaal * GAP_FACTOR), GAP_MINIMUM.total_seconds())
        for i in range(1, len(tijden)):
            verschil = (tijden[i] - tijden[i - 1]).total_seconds()
            if normaal > 0 and verschil > grens:
                gaten.append(
                    f"{pool}: {int(verschil)}s stil vanaf {tijden[i - 1].isoformat()}"
                )

        prijzen = [
            Decimal(str(tick["price_usd"]))
            for tick in reeks
            if tick.get("price_usd") is not None
        ]
        positief = [p for p in prijzen if p > 0]
        mediaan = (
            Decimal(str(statistics.median(sorted(positief)))) if positief else Decimal("0")
        )
        for tick in reeks:
            prijs = tick.get("price_usd")
            tijd = tick["observed_at"]
            if prijs is not None and Decimal(str(prijs)) <= 0:
                nulprijzen.append(f"{pool}@{tijd.isoformat()}={prijs}")
            elif (
                prijs is not None
                and mediaan > 0
                and mediaan < Decimal("1")
                and _is_grof_afgerond(Decimal(str(prijs)), mediaan)
            ):
                afgerond.append(f"{pool}@{tijd.isoformat()}={prijs}")

            # Een tijdstip in de toekomst wordt afgemeten aan het moment waarop we het
            # event kregen, en niet aan "nu": een opname van vorige week hoort later niet
            # ineens vol toekomstige events te staan. Daarnaast nog de controle tegen nu,
            # voor een bron die vooruit loopt op onze eigen klok.
            ontvangen = tick.get("received_at")
            grens_vooruit = timedelta(seconds=FUTURE_TOLERANCE_SECONDS)
            if tijd > now + grens_vooruit or (
                ontvangen is not None and tijd > ontvangen + grens_vooruit
            ):
                toekomst.append(f"{pool}@{tijd.isoformat()}")
            if ontvangen is not None and (
                (ontvangen - tijd).total_seconds() > STALE_SECONDS
            ):
                traag.append(
                    f"{pool}@{tijd.isoformat()} ({int((ontvangen - tijd).total_seconds())}s later)"
                )

    totaal = len(ticks)
    rauw = []
    for check, treffers, altijd_alarm in (
        (DataCheck.GAP, gaten, False),
        (DataCheck.ZERO_OR_NEGATIVE_PRICE, nulprijzen, True),
        (DataCheck.ROUNDED_PRICE, afgerond, False),
        (DataCheck.OUT_OF_ORDER, verkeerde_volgorde, False),
        (DataCheck.FUTURE_TIMESTAMP, toekomst, True),
        (DataCheck.STALE_FEED, traag, False),
    ):
        if treffers:
            rauw.append(
                Finding(
                    check=check,
                    count=len(treffers),
                    severity=_ernst(len(treffers), totaal, altijd_alarm=altijd_alarm),
                    explanation=CHECK_UITLEG[check],
                    examples=tuple(treffers[:3]),
                )
            )

    if duplicates:
        rauw.append(
            Finding(
                check=DataCheck.DUPLICATE,
                count=duplicates,
                severity=_ernst(duplicates, max(raw_count, 1)),
                explanation=CHECK_UITLEG[DataCheck.DUPLICATE],
                examples=(f"{duplicates} dubbele events in de ruwe opslag",),
            )
        )
    if parse_failures:
        rauw.append(
            Finding(
                check=DataCheck.PARSE_FAILURE,
                count=parse_failures,
                severity=_ernst(parse_failures, max(raw_count, 1)),
                explanation=CHECK_UITLEG[DataCheck.PARSE_FAILURE],
                examples=(f"{parse_failures} onleesbare events",),
            )
        )

    bevindingen = tuple(rauw)
    oordeel = QualityVerdict.OK
    if any(b.severity is QualityVerdict.ALARM for b in bevindingen):
        oordeel = QualityVerdict.ALARM
    elif bevindingen:
        oordeel = QualityVerdict.WARNING

    uitleg = VERDICT_UITLEG[oordeel]
    if synthetic_events:
        # Dit is geen bevinding maar een waarschuwing over de herkomst, en die hoort
        # bovenaan: verzonnen data mag nooit per ongeluk voor een resultaat doorgaan.
        uitleg = (
            f"{uitleg} Let op: {synthetic_events} van de {raw_count} events zijn "
            "synthetisch (verzonnen) en zeggen niets over de markt."
        )

    tijden = [tick["observed_at"] for tick in ticks]
    return DataQualityReport(
        verdict=oordeel,
        explanation=uitleg,
        ticks=totaal,
        raw_events=raw_count,
        pools=len([p for p in per_pool if p]),
        synthetic_events=synthetic_events,
        first_observed_at=min(tijden) if tijden else None,
        last_observed_at=max(tijden) if tijden else None,
        findings=bevindingen,
    )


def _is_grof_afgerond(prijs: Decimal, mediaan: Decimal) -> bool:
    """Is deze prijs grover afgerond dan bij deze pool past?

    Een pool die rond de 0,000004 handelt en ineens 0,01 meldt, is niet gestegen maar
    afgerond. De maat is het aantal decimalen: past de prijs op twee decimalen terwijl de
    mediaan er meer nodig heeft, dan is er informatie weggevallen.
    """
    if prijs <= 0:
        return False
    if prijs != prijs.quantize(Decimal("0.01")):
        return False
    return mediaan != mediaan.quantize(Decimal("0.01"))
