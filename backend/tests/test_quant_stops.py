"""De stopafstand per trade (vervangt het vaste percentage).

Een vast percentage was een gok: de opdracht noemt "harde stop op -1R" maar geen afstand,
en zonder afstand is er geen positiegrootte. Nu wordt de stop per trade afgeleid uit wat
dát token zelf deed — de bodem van het venster waar de koers uit kwam.

Deterministische code, geen taalmodel. Dit zit in het pad waarin een trade tot stand komt,
en daar hoort niets in dat kan wachten, kan falen of kan antwoorden met iets anders dan
afgesproken (sectie 6).

De ondergrens van 20% is niet gekozen maar **afgeleid**; zie
`test_de_ondergrens_volgt_uit_het_kostenmodel`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.quantlab.stops import (
    MIN_DISTANCE_DERIVATION,
    StopKind,
    StopRule,
    place_stop,
    slippage_share_of_r,
)


def structureel(**kwargs) -> StopRule:
    opties = dict(
        kind=StopKind.STRUCTURAL_RANGE,
        window_minutes=10,
        margin_pct=Decimal("0.02"),
        min_distance_pct=Decimal("0.20"),
        max_distance_pct=Decimal("0.50"),
    )
    opties.update(kwargs)
    return StopRule(**opties)


# --- Het vaste percentage blijft bestaan, om tegen te kunnen vergelijken -------


def test_een_vaste_stop_doet_precies_wat_hij_zegt() -> None:
    plaatsing = place_stop(
        StopRule(kind=StopKind.FIXED, distance_pct=Decimal("0.25")),
        entry_price=Decimal("1.00"),
    )
    assert plaatsing.stop_price == Decimal("0.75")
    assert plaatsing.distance_pct == Decimal("0.25")
    assert plaatsing.clamped is None
    assert "vast" in plaatsing.basis.lower()


def test_een_vaste_stop_zonder_afstand_is_een_fout() -> None:
    with pytest.raises(ValueError):
        place_stop(StopRule(kind=StopKind.FIXED), entry_price=Decimal("1.00"))


# --- De structurele stop ------------------------------------------------------


def test_de_stop_gaat_onder_de_bodem_van_het_venster() -> None:
    """De trade is weerlegd als de koers terugvalt door het bereik waar hij uit kwam."""
    plaatsing = place_stop(
        structureel(),
        entry_price=Decimal("1.00"),
        window_low=Decimal("0.80"),
        window_high=Decimal("1.00"),
    )
    # 2% onder een bodem van 0,80 is 0,784; de afstand is dan 21,6%.
    assert plaatsing.stop_price == Decimal("0.784")
    assert plaatsing.distance_pct == Decimal("0.216")
    assert plaatsing.clamped is None
    assert "bodem" in plaatsing.basis.lower()


def test_twee_tokens_krijgen_een_verschillende_stop() -> None:
    """Dit is het hele punt: de stop schaalt mee met hoe wild dat token beweegt."""
    rustig = place_stop(
        structureel(), entry_price=Decimal("1.00"), window_low=Decimal("0.75")
    )
    wild = place_stop(
        structureel(), entry_price=Decimal("1.00"), window_low=Decimal("0.55")
    )
    assert rustig.distance_pct < wild.distance_pct
    assert rustig.stop_price > wild.stop_price


def test_een_krappe_bodem_wordt_opgetrokken_naar_de_ondergrens() -> None:
    """Een bodem net onder de instap zou een enorme positie opleveren, en dan eet de
    slippage je hele 1R op. Zie `test_de_ondergrens_volgt_uit_het_kostenmodel`."""
    plaatsing = place_stop(
        structureel(), entry_price=Decimal("1.00"), window_low=Decimal("0.99")
    )
    assert plaatsing.distance_pct == Decimal("0.20")
    assert plaatsing.clamped == "min"
    assert "ondergrens" in plaatsing.basis.lower()


def test_een_wijde_bodem_wordt_teruggebracht_naar_de_bovengrens() -> None:
    """Een stop van 70% betekent dat de helft pas bij +140% eruit gaat. Dan is het geen
    trade meer maar een lot."""
    plaatsing = place_stop(
        structureel(), entry_price=Decimal("1.00"), window_low=Decimal("0.25")
    )
    assert plaatsing.distance_pct == Decimal("0.50")
    assert plaatsing.clamped == "max"


def test_zonder_geschiedenis_valt_de_stop_terug_op_de_ondergrens() -> None:
    """Een token zonder venster erachter mag geen crash geven en ook geen gok: de
    ondergrens is de voorzichtigste bruikbare waarde."""
    plaatsing = place_stop(structureel(), entry_price=Decimal("1.00"), window_low=None)
    assert plaatsing.distance_pct == Decimal("0.20")
    assert plaatsing.clamped == "min"
    assert "geen" in plaatsing.basis.lower()


def test_een_bodem_boven_de_instap_wordt_niet_als_stop_gebruikt() -> None:
    """Bij een willekeurige instap kan de koers net onder de bodem van het venster zitten.
    Een stop bóven de instap is geen stop."""
    plaatsing = place_stop(
        structureel(), entry_price=Decimal("1.00"), window_low=Decimal("1.20")
    )
    assert plaatsing.stop_price < Decimal("1.00")
    assert plaatsing.distance_pct == Decimal("0.20")
    assert plaatsing.clamped == "min"


def test_de_stop_ligt_altijd_onder_de_instap_en_boven_nul() -> None:
    for bodem in ("0.01", "0.10", "0.50", "0.90", "0.99", "1.50"):
        plaatsing = place_stop(
            structureel(), entry_price=Decimal("1.00"), window_low=Decimal(bodem)
        )
        assert Decimal("0") < plaatsing.stop_price < Decimal("1.00"), bodem
        assert plaatsing.distance > 0


def test_een_instapprijs_van_nul_of_lager_is_een_fout() -> None:
    for prijs in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            place_stop(structureel(), entry_price=prijs, window_low=Decimal("0.5"))


# --- Waar de ondergrens vandaan komt -----------------------------------------


def test_de_slippage_als_deel_van_1r_hangt_omgekeerd_aan_de_stopafstand() -> None:
    """De rekensom die de ondergrens bepaalt.

    Bij een pool die precies aan het filter "liquiditeit minstens 50x de positie" voldoet,
    is de quote-kant 25x de positie, en de price impact van een constant-product pool is
    ongeveer inleg/quote-kant = 1/25 = 4%. De positie is 1R/stopafstand, dus de slippage
    kost 0,04/stopafstand van je 1R. Hoe krapper de stop, hoe meer van je risicobudget
    opgaat voordat de trade iets heeft gedaan."""
    assert slippage_share_of_r(Decimal("0.25"), liquidity_multiple=Decimal("50")) == Decimal(
        "0.16"
    )
    assert slippage_share_of_r(Decimal("0.10"), liquidity_multiple=Decimal("50")) == Decimal(
        "0.40"
    )
    assert slippage_share_of_r(Decimal("0.50"), liquidity_multiple=Decimal("50")) == Decimal(
        "0.08"
    )


def test_een_diepere_pool_is_goedkoper() -> None:
    krap = slippage_share_of_r(Decimal("0.25"), liquidity_multiple=Decimal("50"))
    diep = slippage_share_of_r(Decimal("0.25"), liquidity_multiple=Decimal("200"))
    assert diep < krap


def test_de_ondergrens_volgt_uit_het_kostenmodel() -> None:
    """20% is niet gekozen maar afgeleid: het is de krapste stop waarbij de slippage op een
    pool aan de liquiditeitsgrens onder 20% van 1R blijft.

    Dat is het enige getal in de stopregel met een afleiding erachter, en daarom staat die
    afleiding in de code en niet alleen in een rapport."""
    assert MIN_DISTANCE_DERIVATION["budget_share_of_r"] == Decimal("0.20")
    assert MIN_DISTANCE_DERIVATION["liquidity_multiple"] == Decimal("50")
    assert MIN_DISTANCE_DERIVATION["min_distance_pct"] == Decimal("0.20")
    # En de som klopt ook werkelijk.
    assert slippage_share_of_r(
        MIN_DISTANCE_DERIVATION["min_distance_pct"],
        liquidity_multiple=MIN_DISTANCE_DERIVATION["liquidity_multiple"],
    ) <= MIN_DISTANCE_DERIVATION["budget_share_of_r"]
