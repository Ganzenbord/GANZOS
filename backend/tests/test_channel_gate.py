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
    uitkomst = evaluate(
        (maand(2026, 10, "3200"), maand(2026, 11, "3500"), maand(2026, 12, "6500")),
        rule_for_channel(2),
        today=date(2027, 1, 15),
    )
    assert uitkomst.passed is False
    # En het scherm kan uitleggen waarom het tóch niet doorgaat.
    assert uitkomst.latest_month_would_pass is True
    assert "2026-10, 2026-11" in uitkomst.explanation
    # December is een piekmaand, dus die opmerking hoort er hier wél bij.
    assert "piekmaand" in uitkomst.explanation


def test_een_venster_dat_helemaal_in_de_piek_valt_krijgt_een_waarschuwing() -> None:
    uitkomst = evaluate(
        (maand(2026, 11, "6200"), maand(2026, 12, "7000")),
        GateRule(threshold=Decimal("6000"), window_months=2),
        today=date(2027, 1, 10),
    )
    # Allebei boven de grens, dus de poort gaat open — maar niet zonder de waarschuwing.
    assert uitkomst.passed is True
    assert uitkomst.season_warning is not None
    assert "álle maanden" in uitkomst.season_warning


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


def test_gemiddeld_zesduizend_is_niet_hetzelfde_als_consistent_zesduizend() -> None:
    """Dit is het verschil tussen de twee regels, en de reden dat Stef de strengere koos.

    €1.000, €1.000 en €16.000 is gemiddeld precies €6.000. Het is geen kanaal dat €6.000 per
    maand verdient; het is een kanaal met één uitschieter. Op een gemiddelde zou de poort
    hier opengaan."""
    cijfers = (maand(2027, 3, "1000"), maand(2027, 4, "1000"), maand(2027, 5, "16000"))

    streng = evaluate(cijfers, rule_for_channel(2), today=date(2027, 6, 2))
    assert streng.trailing_average == Decimal("6000")
    assert streng.passed is False
    assert "niet gemiddeld" in streng.explanation

    # En zo zou het zijn gegaan met de zachtere regel: precies de verkeerde beslissing.
    zacht = evaluate(
        cijfers,
        GateRule(threshold=Decimal("6000"), window_months=3, every_month=False),
        today=date(2027, 6, 2),
    )
    assert zacht.passed is True


def test_drie_maanden_achter_elkaar_net_boven_de_grens_haalt_het_wel() -> None:
    """Consistent betekent niet "ruim": precies de grens is genoeg, drie maanden achter
    elkaar."""
    uitkomst = evaluate(
        (maand(2027, 3, "6000"), maand(2027, 4, "6000"), maand(2027, 5, "6000")),
        rule_for_channel(2),
        today=date(2027, 6, 2),
    )
    assert uitkomst.passed is True
    assert "achter elkaar" in uitkomst.explanation


def test_een_maand_net_onder_de_grens_houdt_de_poort_dicht() -> None:
    """Eén euro te weinig is te weinig. Een regel met een onduidelijke rand is geen regel."""
    uitkomst = evaluate(
        (maand(2027, 3, "6000"), maand(2027, 4, "5999"), maand(2027, 5, "9000")),
        rule_for_channel(2),
        today=date(2027, 6, 2),
    )
    assert uitkomst.passed is False
    assert "2027-04" in uitkomst.explanation


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


# --- De uitleg moet waar zijn, niet alleen behulpzaam ------------------------


def test_de_decemberopmerking_staat_er_alleen_bij_een_piekmaand() -> None:
    """Deze tekst stond er eerst altijd bij. Bij een uitschieter in mei is "juist in
    december" gewoon niet waar, en een uitleg die niet klopt is erger dan geen uitleg."""
    mei = evaluate(
        (maand(2027, 3, "1000"), maand(2027, 4, "1000"), maand(2027, 5, "16000")),
        rule_for_channel(2),
        today=date(2027, 6, 2),
    )
    assert mei.latest_month_would_pass is True
    assert "piekmaand" not in mei.explanation

    december = evaluate(
        (maand(2026, 10, "1000"), maand(2026, 11, "1000"), maand(2026, 12, "16000")),
        rule_for_channel(2),
        today=date(2027, 1, 5),
    )
    assert "piekmaand" in december.explanation


def test_beslissen_op_het_hoogtepunt_krijgt_de_zwaarste_waarschuwing() -> None:
    """Drie maanden consistent boven de grens, maar de laatste is december: dan sta je op
    het hoogtepunt van het jaar te beslissen en is de maand erna per definitie slechter."""
    uitkomst = evaluate(
        (maand(2026, 10, "6100"), maand(2026, 11, "6400"), maand(2026, 12, "8000")),
        rule_for_channel(2),
        today=date(2027, 1, 5),
    )
    assert uitkomst.passed is True
    assert uitkomst.season_warning is not None
    assert "hoogtepunt" in uitkomst.season_warning
    assert "20 tot 50 procent" in uitkomst.season_warning


def test_de_waarschuwing_praat_niet_over_het_gemiddelde() -> None:
    """Het gemiddelde beslist niet meer, dus een waarschuwing erover stuurt je de verkeerde
    kant op."""
    uitkomst = evaluate(
        (maand(2026, 11, "6200"), maand(2026, 12, "7000")),
        GateRule(threshold=Decimal("6000"), window_months=2),
        today=date(2027, 1, 10),
    )
    assert uitkomst.season_warning is not None
    assert "gemiddelde" not in uitkomst.season_warning
