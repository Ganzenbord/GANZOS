"""De poort waarmee het volgende kanaal opengaat.

Stefs regel: kanaal 2 begint pas als kanaal 1 minstens €6.000 per maand haalt, daarna
€3.000. De tests hieronder gaan niet over het optellen — ze gaan over de twee manieren
waarop zo'n regel stil fout gaat: de decemberpiek, en de maand die nog loopt.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.channels.gate import (
    CurrencyMismatch,
    GateRule,
    Measurement,
    MonthRevenue,
    evaluate,
    monthly_totals,
    rule_for_channel,
)


def maand(jaar: int, nr: int, bedrag: str) -> MonthRevenue:
    return MonthRevenue(year=jaar, month=nr, amount=Decimal(bedrag))


def meting(jaar: int, nr: int, dag: int, bedrag: str, valuta: str = "EUR") -> Measurement:
    return Measurement(
        measured_at=datetime(jaar, nr, dag, 12, tzinfo=timezone.utc),
        revenue=Decimal(bedrag),
        currency=valuta,
    )


# --- De decemberval ----------------------------------------------------------


def test_een_decembermaand_opent_de_poort_niet_in_zijn_eentje() -> None:
    """Dit is de belangrijkste test van dit bestand.

    De advertentietarieven zijn in december het hoogst van het jaar en in januari het
    laagst. Een poort die op één maand afgaat, gaat dus elke december open en blijkt elke
    januari te vroeg."""
    # Boven de ondergrens per maand, zodat deze test alléén over de decemberpiek gaat en
    # niet per ongeluk op de ondergrens afketst.
    uitkomst = evaluate(
        (maand(2026, 10, "3200"), maand(2026, 11, "3500"), maand(2026, 12, "6500")),
        rule_for_channel(2),
        today=date(2027, 1, 15),
    )
    assert uitkomst.passed is False
    # En het scherm kan uitleggen waarom het tóch niet doorgaat.
    assert uitkomst.latest_month_would_pass is True
    assert "geen trend" in uitkomst.explanation
    assert "december" in uitkomst.explanation


def test_een_venster_dat_helemaal_in_de_piek_valt_krijgt_een_waarschuwing() -> None:
    uitkomst = evaluate(
        (maand(2026, 11, "6200"), maand(2026, 12, "7000")),
        GateRule(threshold=Decimal("6000"), window_months=2),
        today=date(2027, 1, 10),
    )
    assert uitkomst.passed is True
    assert uitkomst.season_warning is not None
    assert "geflatteerd" in uitkomst.season_warning


def test_een_gewoon_venster_krijgt_geen_waarschuwing() -> None:
    uitkomst = evaluate(
        (maand(2027, 3, "6100"), maand(2027, 4, "6400"), maand(2027, 5, "6300")),
        rule_for_channel(2),
        today=date(2027, 6, 5),
    )
    assert uitkomst.passed is True
    assert uitkomst.season_warning is None
    assert "poort is open" in uitkomst.explanation


# --- De maand die nog loopt --------------------------------------------------


def test_de_lopende_maand_telt_niet_mee() -> None:
    """YouTube geeft omzet van de eerste van de maand tot vandaag. Die meetellen zou
    betekenen dat je op de derde van de maand naar drie dagen omzet kijkt en concludeert dat
    het kanaal instort."""
    maanden = monthly_totals(
        [
            meting(2027, 3, 31, "6200"),
            meting(2027, 4, 30, "6400"),
            meting(2027, 5, 3, "600"),  # drie dagen van de lopende maand
        ],
        today=date(2027, 5, 3),
    )
    assert [m.label for m in maanden] == ["2027-03", "2027-04"]
    assert maanden[-1].amount == Decimal("6400")


def test_per_maand_geldt_de_laatste_meting() -> None:
    """Elke meting is een stand-tot-nu, dus de laatste van de maand is het maandtotaal.
    Zou je ze optellen, dan komt de omzet van een maand vele malen te hoog uit."""
    maanden = monthly_totals(
        [
            meting(2027, 3, 5, "900"),
            meting(2027, 3, 15, "3100"),
            meting(2027, 3, 31, "6200"),
        ],
        today=date(2027, 4, 2),
    )
    assert len(maanden) == 1
    assert maanden[0].amount == Decimal("6200")


def test_metingen_in_de_verkeerde_valuta_worden_geweigerd() -> None:
    """Omrekenen hoort hier niet te gebeuren. In dit project is één keer een koers de
    verkeerde kant op gegaan, en dat kostte een positie van 15% te klein zonder dat iemand
    het zag."""
    with pytest.raises(CurrencyMismatch):
        monthly_totals([meting(2027, 3, 31, "6200", valuta="USD")], today=date(2027, 4, 2))


# --- De regel zelf -----------------------------------------------------------


def test_te_weinig_maanden_is_geen_nee_maar_te_vroeg() -> None:
    uitkomst = evaluate(
        (maand(2027, 4, "9000"),), rule_for_channel(2), today=date(2027, 5, 2)
    )
    assert uitkomst.passed is False
    assert "te vroeg" in uitkomst.explanation
    assert "2 maand" in uitkomst.explanation


def test_een_uitschieter_tussen_twee_magere_maanden_haalt_het_niet() -> None:
    """Gemiddeld €6.000, maar twee van de drie maanden ver onder de helft. Zonder
    ondergrens per maand zou dit de poort openen."""
    uitkomst = evaluate(
        (maand(2027, 3, "1000"), maand(2027, 4, "1000"), maand(2027, 5, "16000")),
        rule_for_channel(2),
        today=date(2027, 6, 2),
    )
    assert uitkomst.trailing_average == Decimal("6000")
    assert uitkomst.passed is False
    assert "ondergrens" in uitkomst.explanation


def test_het_derde_kanaal_heeft_een_lagere_poort() -> None:
    """Met één kanaal weet je niet of de machine werkt of deze ene niche. Met twee wel, dus
    mag de grens lager."""
    cijfers = (maand(2027, 3, "3200"), maand(2027, 4, "3400"), maand(2027, 5, "3300"))
    assert evaluate(cijfers, rule_for_channel(3), today=date(2027, 6, 2)).passed is True
    # Dezelfde cijfers openen de poort voor kanaal 2 niet.
    assert evaluate(cijfers, rule_for_channel(2), today=date(2027, 6, 2)).passed is False


def test_het_eerste_kanaal_heeft_geen_poort() -> None:
    with pytest.raises(ValueError):
        rule_for_channel(1)


def test_zonder_cijfers_is_het_antwoord_te_vroeg_en_geen_nul() -> None:
    uitkomst = evaluate((), rule_for_channel(2), today=date(2027, 6, 2))
    assert uitkomst.passed is False
    assert uitkomst.months_measured == 0
    assert "te vroeg" in uitkomst.explanation
