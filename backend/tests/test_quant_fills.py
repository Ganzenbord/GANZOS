"""Het fill-model (sectie 10). Unit tests, want dit is waar paper trading om zeep gaat.

Memecoin-paper-trading is berucht om onrealistische fills: je rekent met de prijs op het
moment van het signaal, zonder vertraging, zonder slippage, zonder fee, zonder mislukte
transacties — en dan komt er een curve uit die niets met de werkelijkheid te maken heeft.

Elk van die vijf dingen heeft hieronder een test. En één test die de hele boel bij elkaar
houdt: een fill mag nooit gunstiger zijn dan de prijs waarop je mikte.

**Geen van de kostenparameters is geverifieerd.** Ze staan in de hypothese-bestanden met
hun herkomst erbij ("niet geverifieerd — na te meten uit ..."). Deze tests gaan dus over de
vorm van het model, niet over de hoogte van de kosten.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.quantlab.fills import (
    STRESS_PROFILES,
    FillKind,
    FillModel,
    FillRequest,
    FillOutcome,
    PoolDepth,
    StressProfile,
    latency_for_quantile,
    pool_depth_from_liquidity,
    price_impact,
)

NU = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)

KOSTEN = dict(
    swap_fee_bps=30,
    priority_fee_usd=Decimal("0.05"),
    network_fee_usd=Decimal("0.001"),
    failure_probability=0.05,
    latency_p50_ms=800,
    latency_p95_ms=3000,
    exit_haircut_bps=150,
    exit_haircut_above_pool_share=Decimal("0.01"),
)


def model(**overschrijf) -> FillModel:
    return FillModel(**{**KOSTEN, **overschrijf})


def pool(liquidity: str = "50000", price: str = "0.001") -> PoolDepth:
    return pool_depth_from_liquidity(
        liquidity_usd=Decimal(liquidity), spot_price=Decimal(price)
    )


def koop(usd: str = "100", **kwargs) -> FillRequest:
    opties = dict(
        kind=FillKind.ENTRY,
        requested_at=NU,
        expected_price=Decimal("0.001"),
        quote_usd=Decimal(usd),
        pool=pool(),
    )
    opties.update(kwargs)
    return FillRequest(**opties)


# --- Pooldiepte en slippage ---------------------------------------------------


def test_de_pooldiepte_volgt_uit_de_liquiditeit() -> None:
    """Een constant-product pool heeft de helft van zijn waarde aan elke kant.

    Dat is geen aanname van mij maar hoe zo'n pool werkt: de gerapporteerde liquiditeit is
    de totale waarde, dus de quote-kant is de helft. Daaruit volgt de token-kant uit de
    spotprijs."""
    diepte = pool_depth_from_liquidity(
        liquidity_usd=Decimal("50000"), spot_price=Decimal("0.001")
    )
    assert diepte.quote_reserve == Decimal("25000")
    # 25.000 dollar aan de quote-kant bij een prijs van 0,001 is 25 miljoen tokens.
    assert diepte.token_reserve == Decimal("25000000")
    assert diepte.spot_price == Decimal("0.001")


def test_een_grotere_order_kost_meer_slippage() -> None:
    """De kern van price impact: hoe meer je van de pool neemt, hoe slechter je prijs."""
    diepte = pool()
    klein = price_impact(diepte, quote_usd=Decimal("10"), swap_fee_bps=0)
    groot = price_impact(diepte, quote_usd=Decimal("5000"), swap_fee_bps=0)
    assert 0 < klein < groot
    # Een order van 10% van de quote-kant hoort echt te schuren.
    assert groot > Decimal("0.15")


def test_slippage_is_nooit_negatief() -> None:
    """Een order die jou een betere prijs geeft dan de spot, bestaat niet in een AMM."""
    assert price_impact(pool(), quote_usd=Decimal("1"), swap_fee_bps=0) >= 0


def test_een_order_van_niets_heeft_geen_slippage() -> None:
    assert price_impact(pool(), quote_usd=Decimal("0"), swap_fee_bps=0) == 0


def test_de_fee_komt_boven_op_de_slippage() -> None:
    zonder = price_impact(pool(), quote_usd=Decimal("100"), swap_fee_bps=0)
    met = price_impact(pool(), quote_usd=Decimal("100"), swap_fee_bps=30)
    assert met > zonder
    # 30 basispunten is 0,3%; met een kleine order is de slippage klein, dus het verschil
    # hoort dicht bij die 0,3% te liggen.
    assert (met - zonder) == pytest.approx(Decimal("0.003"), abs=Decimal("0.0005"))


def test_een_lege_pool_laat_geen_order_toe() -> None:
    leeg = pool_depth_from_liquidity(
        liquidity_usd=Decimal("0"), spot_price=Decimal("0.001")
    )
    with pytest.raises(ValueError):
        price_impact(leeg, quote_usd=Decimal("100"), swap_fee_bps=30)


# --- Vertraging ---------------------------------------------------------------


def test_de_vertraging_raakt_de_opgegeven_percentielen() -> None:
    """p50 en p95 uit de config moeten er ook echt uitkomen, anders is de config een leugen."""
    assert latency_for_quantile(0.5, p50_ms=800, p95_ms=3000) == pytest.approx(800, rel=0.01)
    assert latency_for_quantile(0.95, p50_ms=800, p95_ms=3000) == pytest.approx(3000, rel=0.02)


def test_de_vertraging_loopt_op_met_het_percentiel() -> None:
    vorige = 0.0
    for q in (0.05, 0.25, 0.5, 0.75, 0.95, 0.99):
        nu = latency_for_quantile(q, p50_ms=800, p95_ms=3000)
        assert nu > vorige
        vorige = nu


def test_een_fill_gebeurt_na_de_vertraging_en_niet_ervoor() -> None:
    """Fillen op de prijs van het signaalmoment is precies de fout die dit model voorkomt."""
    uitkomst = model().fill(koop(), seed=1, price_after=lambda moment: Decimal("0.001"))
    assert uitkomst.filled_at > uitkomst.requested_at
    assert uitkomst.latency_ms > 0


def test_de_prijs_na_de_vertraging_is_de_prijs_waarop_wordt_gevuld() -> None:
    """Loopt de prijs in die 800 milliseconden weg, dan koop je op de nieuwe prijs."""
    uitkomst = model(failure_probability=0.0).fill(
        koop(), seed=1, price_after=lambda moment: Decimal("0.0012")
    )
    assert uitkomst.filled is True
    # 20% weggelopen plus slippage en fee: de fill ligt boven 0,0012.
    assert uitkomst.fill_price > Decimal("0.0012")
    assert uitkomst.expected_price == Decimal("0.001")


def test_zonder_prijs_na_de_vertraging_vervalt_het_signaal() -> None:
    """De data stopt, of het token is weg. Dan is er geen fill, en dat moet geteld worden."""
    uitkomst = model().fill(koop(), seed=1, price_after=lambda moment: None)
    assert uitkomst.filled is False
    assert uitkomst.failure_reason == "no_price_after_latency"


# --- Mislukte transacties -----------------------------------------------------


def test_een_mislukte_transactie_kost_wel_geld() -> None:
    """Op een chain betaal je de tip en de netwerkkosten ook als je transactie faalt.

    Dat is geen detail: bij een strategie die veel probeert en weinig raakt, zijn juist die
    mislukte pogingen de kostenpost."""
    uitkomst = model(failure_probability=1.0).fill(
        koop(), seed=1, price_after=lambda moment: Decimal("0.001")
    )
    assert uitkomst.filled is False
    assert uitkomst.failure_reason == "transaction_failed"
    assert uitkomst.fee_usd == Decimal("0.051")
    assert uitkomst.units == 0


def test_zonder_kans_op_falen_lukt_elke_transactie() -> None:
    for seed in range(20):
        uitkomst = model(failure_probability=0.0).fill(
            koop(), seed=seed, price_after=lambda moment: Decimal("0.001")
        )
        assert uitkomst.filled is True


def test_de_kans_op_falen_komt_ongeveer_uit() -> None:
    """Niet exact — het is kans — maar wel in de buurt, anders is de parameter zinloos."""
    mislukt = sum(
        0 if model(failure_probability=0.2)
        .fill(koop(), seed=seed, price_after=lambda moment: Decimal("0.001"))
        .filled
        else 1
        for seed in range(400)
    )
    assert 0.12 < mislukt / 400 < 0.28


# --- Uitstappen ---------------------------------------------------------------


def test_uitstappen_levert_minder_op_dan_de_spotprijs() -> None:
    uitkomst = model(failure_probability=0.0).fill(
        FillRequest(
            kind=FillKind.EXIT,
            requested_at=NU,
            expected_price=Decimal("0.001"),
            units=Decimal("100000"),
            pool=pool(),
        ),
        seed=1,
        price_after=lambda moment: Decimal("0.001"),
    )
    assert uitkomst.filled is True
    assert uitkomst.fill_price < Decimal("0.001")


def test_een_grote_positie_krijgt_een_haircut_op_de_uitstap() -> None:
    """Boven een deel van de pool geldt een extra haircut: in paniek krijg je slechter dan
    de AMM-curve je voorrekent. Bewust conservatief."""

    def uit(units: str) -> FillOutcome:
        return model(failure_probability=0.0).fill(
            FillRequest(
                kind=FillKind.EXIT,
                requested_at=NU,
                expected_price=Decimal("0.001"),
                units=Decimal(units),
                pool=pool(),
            ),
            seed=1,
            price_after=lambda moment: Decimal("0.001"),
        )

    # 100.000 tokens à 0,001 = 100 dollar, dat is 0,2% van een pool van 50.000: geen haircut.
    klein = uit("100000")
    # 1.000.000 tokens = 1.000 dollar, dat is 2%: wel haircut.
    groot = uit("1000000")
    assert klein.exit_haircut_applied is False
    assert groot.exit_haircut_applied is True


def test_een_haircut_maakt_de_uitstap_slechter_en_niet_beter() -> None:
    def uit(haircut: int) -> Decimal:
        uitkomst = model(failure_probability=0.0, exit_haircut_bps=haircut).fill(
            FillRequest(
                kind=FillKind.EXIT,
                requested_at=NU,
                expected_price=Decimal("0.001"),
                units=Decimal("1000000"),
                pool=pool(),
            ),
            seed=1,
            price_after=lambda moment: Decimal("0.001"),
        )
        return uitkomst.fill_price

    assert uit(300) < uit(150) < uit(0)


# --- De afspraak die alles bij elkaar houdt ----------------------------------


@pytest.mark.parametrize("seed", range(25))
def test_een_fill_is_nooit_gunstiger_dan_de_verwachte_prijs(seed: int) -> None:
    """Dit is de belangrijkste test in dit bestand.

    Een paper broker die soms een betere prijs geeft dan waarop je mikte, verzint geld. Bij
    een instap moet de fill hoger liggen (je betaalt meer), bij een uitstap lager (je krijgt
    minder) — tenzij de prijs zelf in jouw richting liep, en dan nog steeds met kosten erop.
    Hier staat de prijs stil, dus de enige beweging kan van de kosten komen."""
    broker = model(failure_probability=0.0)
    instap = broker.fill(koop(), seed=seed, price_after=lambda m: Decimal("0.001"))
    assert instap.fill_price >= instap.expected_price
    assert instap.slippage_usd >= 0

    uitstap = broker.fill(
        FillRequest(
            kind=FillKind.EXIT,
            requested_at=NU,
            expected_price=Decimal("0.001"),
            units=Decimal("100000"),
            pool=pool(),
        ),
        seed=seed,
        price_after=lambda m: Decimal("0.001"),
    )
    assert uitstap.fill_price <= uitstap.expected_price
    assert uitstap.slippage_usd >= 0


def test_hetzelfde_zaad_geeft_dezelfde_fill() -> None:
    """Zonder dit is een stresstest zinloos: je zou niet weten of het verschil van de
    stress komt of van het toeval."""
    eerst = model().fill(koop(), seed=42, price_after=lambda m: Decimal("0.001"))
    nogmaals = model().fill(koop(), seed=42, price_after=lambda m: Decimal("0.001"))
    assert eerst == nogmaals


# --- Stresstest ---------------------------------------------------------------


def test_de_vier_stressvarianten_staan_vast() -> None:
    """Sectie 10: alle resultaten ook onder 2x slippage en 2x latency."""
    assert set(STRESS_PROFILES) == {"base", "slippage_2x", "latency_2x", "both_2x"}
    assert STRESS_PROFILES["base"] == StressProfile(
        slippage_multiplier=Decimal("1"), latency_multiplier=Decimal("1")
    )
    assert STRESS_PROFILES["both_2x"] == StressProfile(
        slippage_multiplier=Decimal("2"), latency_multiplier=Decimal("2")
    )


def test_twee_keer_slippage_maakt_de_instap_duurder() -> None:
    basis = model(failure_probability=0.0, stress=STRESS_PROFILES["base"])
    zwaar = model(failure_probability=0.0, stress=STRESS_PROFILES["slippage_2x"])
    a = basis.fill(koop("1000"), seed=3, price_after=lambda m: Decimal("0.001"))
    b = zwaar.fill(koop("1000"), seed=3, price_after=lambda m: Decimal("0.001"))
    assert b.fill_price > a.fill_price
    assert b.slippage_usd > a.slippage_usd


def test_twee_keer_latency_laat_de_fill_later_vallen() -> None:
    basis = model(failure_probability=0.0, stress=STRESS_PROFILES["base"])
    traag = model(failure_probability=0.0, stress=STRESS_PROFILES["latency_2x"])
    a = basis.fill(koop(), seed=3, price_after=lambda m: Decimal("0.001"))
    b = traag.fill(koop(), seed=3, price_after=lambda m: Decimal("0.001"))
    assert b.latency_ms == pytest.approx(a.latency_ms * 2, rel=0.01)


def test_stress_verandert_niets_aan_de_kans_op_falen() -> None:
    """De stresstest gaat over slippage en latency. Zou hij ook de faalkans opschroeven,
    dan weet je niet meer waar een slechter resultaat vandaan komt."""
    basis = sum(
        1
        for seed in range(200)
        if not model(failure_probability=0.2, stress=STRESS_PROFILES["base"])
        .fill(koop(), seed=seed, price_after=lambda m: Decimal("0.001"))
        .filled
    )
    zwaar = sum(
        1
        for seed in range(200)
        if not model(failure_probability=0.2, stress=STRESS_PROFILES["both_2x"])
        .fill(koop(), seed=seed, price_after=lambda m: Decimal("0.001"))
        .filled
    )
    assert basis == zwaar
