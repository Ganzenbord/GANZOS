"""De paper broker en de controlegroep H0 (secties 8 en 10).

Drie dingen staan hier op het spel, en ze zijn alle drie makkelijk om per ongeluk fout te
doen:

1. **Pre-registratie.** Een hypothese wordt vastgelegd en gehasht vóór de eerste run.
   Hetzelfde bestand later stilletjes wijzigen is precies wat deze hash moet tegenhouden.
2. **Niet-genomen signalen.** Zonder die log kun je achteraf elke uitkomst mooi praten door
   te vergeten wat je hebt overgeslagen.
3. **De stresstest.** Een edge die 2x slippage niet overleeft, is geen edge.

Het corpus is synthetisch (verzonnen). Deze tests gaan over de machinerie; er staat geen
enkel cijfer in dat iets over de markt zegt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.quantlab.exits import ExitKind, ExitRules, OpenPosition, evaluate_exit
from app.quantlab.fills import STRESS_PROFILES
from app.quantlab.hypothesis import (
    HypothesisFile,
    PreRegistrationError,
    hypothesis_hash,
    load_hypothesis,
)
from app.quantlab.metrics import TradeResult, expectancy, max_drawdown_r
from app.quantlab.safety import (
    AlwaysSafeOracle,
    NeverVerifiableOracle,
    SafetyStatus,
    SyntheticSafetyOracle,
)
from app.quantlab.stops import StopKind, StopRule
from app.quantlab.strategy import Candidate, RandomEntryStrategy
from app.quantlab.synthetic import SyntheticPoolSource

HYPOTHESES = Path(__file__).resolve().parents[2] / "hypotheses"
START = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
UUR = timedelta(hours=1)


def bron(**kwargs) -> SyntheticPoolSource:
    opties = dict(seed=20261007, start_at=START, duration=UUR, pools=3, cadence_seconds=10)
    opties.update(kwargs)
    return SyntheticPoolSource(**opties)


def h0() -> HypothesisFile:
    """De oude vorm met een vaste stop van 25%. Blijft bestaan om tegen te vergelijken."""
    return load_hypothesis(HYPOTHESES / "H0_v1.yaml")


def h0_v2() -> HypothesisFile:
    """De nieuwe vorm: de stop volgt per trade uit wat het token zelf deed."""
    return load_hypothesis(HYPOTHESES / "H0_v2.yaml")


# --- Pre-registratie ----------------------------------------------------------


def test_de_hypothesebestanden_laden() -> None:
    for naam in ("H0_v1", "H1_v1", "H0_v2", "H1_v2"):
        hypothese = load_hypothesis(HYPOTHESES / f"{naam}.yaml")
        assert hypothese.name and hypothese.version
        assert hypothese.statement.strip()
        assert hypothese.paper_only is True, "er wordt in dit project niet live gehandeld"
        assert len(hypothese.content_hash) == 64


def test_de_hash_gaat_over_de_inhoud_van_het_bestand() -> None:
    """Niet over een geparste structuur: dan zou een andere sleutelvolgorde of een gewijzigd
    commentaar ongemerkt doorglippen, en commentaar is hier uitleg die ertoe doet."""
    tekst = (HYPOTHESES / "H0_v1.yaml").read_text()
    assert hypothesis_hash(tekst) == h0().content_hash
    assert hypothesis_hash(tekst + "\n# nog een regel") != h0().content_hash


def test_elke_kostenparameter_heeft_een_herkomst() -> None:
    """Sectie 12: prijzen en kosten komen niet uit het hoofd.

    Geen enkele waarde in het kostenmodel is op dit moment geverifieerd — er is geen bron
    bereikbaar. Dan is het minste wat je kunt doen: per parameter opschrijven waar hij
    vandaan komt en wat er nodig is om hem na te meten."""
    for naam in ("H0_v1", "H1_v1", "H0_v2", "H1_v2"):
        hypothese = load_hypothesis(HYPOTHESES / f"{naam}.yaml")
        assert set(hypothese.cost_model_provenance) == set(hypothese.cost_model), naam
        for sleutel, herkomst in hypothese.cost_model_provenance.items():
            assert len(herkomst) > 20, f"{naam}.{sleutel} heeft geen bruikbare herkomst"


@pytest.mark.parametrize("versie", ["v1", "v2"])
def test_h0_en_h1_hebben_hetzelfde_kostenmodel_en_dezelfde_exits(versie: str) -> None:
    """H0 is de ruisvloer waar H1 tegen wordt afgemeten. Een verschil in kosten of exits zou
    dat vergelijk waardeloos maken: dan meet je twee verschillende dingen.

    Dat geldt ook voor de stopregel: zouden H0 en H1 hun stop anders bepalen, dan verschilt
    de positiegrootte systematisch en vergelijk je twee sizings in plaats van twee
    strategieën."""
    nul = load_hypothesis(HYPOTHESES / f"H0_{versie}.yaml")
    een = load_hypothesis(HYPOTHESES / f"H1_{versie}.yaml")
    assert nul.cost_model == een.cost_model
    assert nul.exit_rules == een.exit_rules
    assert nul.sizing_risk_r == een.sizing_risk_r


async def test_een_hypothese_wordt_gehasht_bij_registratie(session) -> None:
    from app.models.quantlab import QuantHypothesis
    from app.services import quant_paper_service
    from sqlalchemy import select

    rij = await quant_paper_service.register_hypothesis(session, h0())
    await session.commit()

    bewaard = (await session.execute(select(QuantHypothesis))).scalar_one()
    assert bewaard.id == rij.id
    assert bewaard.name == "H0"
    assert bewaard.version == "v1"
    assert bewaard.content_hash == h0().content_hash
    assert bewaard.source_yaml == (HYPOTHESES / "H0_v1.yaml").read_text()


async def test_hetzelfde_bestand_opnieuw_registreren_verandert_niets(session) -> None:
    from app.models.quantlab import QuantHypothesis
    from app.services import quant_paper_service
    from sqlalchemy import func, select

    eerst = await quant_paper_service.register_hypothesis(session, h0())
    await session.commit()
    nogmaals = await quant_paper_service.register_hypothesis(session, h0())
    await session.commit()

    assert eerst.id == nogmaals.id
    assert await session.scalar(select(func.count()).select_from(QuantHypothesis)) == 1


async def test_een_gewijzigd_bestand_onder_dezelfde_versie_wordt_geweigerd(session) -> None:
    """Dit is waar pre-registratie om gaat. Wijzigen betekent een nieuwe versie, en dan
    begint de trade-teller opnieuw — anders kun je achteraf aan de knoppen draaien tot het
    resultaat bevalt."""
    from app.services import quant_paper_service

    await quant_paper_service.register_hypothesis(session, h0())
    await session.commit()

    gesleuteld = h0().with_source(h0().source_yaml + "\n# stiekem iets veranderd\n")
    with pytest.raises(PreRegistrationError) as fout:
        await quant_paper_service.register_hypothesis(session, gesleuteld)
    assert "v2" in str(fout.value) or "nieuwe versie" in str(fout.value).lower()


async def test_een_nieuwe_versie_mag_wel(session) -> None:
    from app.models.quantlab import QuantHypothesis
    from app.services import quant_paper_service
    from sqlalchemy import func, select

    await quant_paper_service.register_hypothesis(session, h0())
    volgende = h0().with_source(h0().source_yaml.replace("version: v1", "version: v2"))
    await quant_paper_service.register_hypothesis(session, volgende)
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(QuantHypothesis)) == 2


# --- De exits -----------------------------------------------------------------


REGELS = ExitRules(
    stop=StopRule(kind=StopKind.FIXED, distance_pct=Decimal("0.25")),
    take_half_at_r=Decimal("2"),
    trailing_stop_pct=Decimal("0.20"),
    max_hold_minutes=240,
)


def positie(**kwargs) -> OpenPosition:
    opties = dict(
        pool_address="pool-1",
        opened_at=START,
        entry_price=Decimal("1.00"),
        units=Decimal("100"),
        stop_price=Decimal("0.75"),
        r_price_distance=Decimal("0.25"),
        risk_quote=Decimal("25"),
        peak_price=Decimal("1.00"),
        half_taken=False,
    )
    opties.update(kwargs)
    return OpenPosition(**opties)


def test_de_stop_sluit_de_positie_op_min_1r() -> None:
    besluit = evaluate_exit(positie(), price=Decimal("0.74"), moment=START, rules=REGELS)
    assert besluit is not None
    assert besluit.kind is ExitKind.STOP
    assert besluit.fraction == Decimal("1")


def test_boven_de_stop_blijft_de_positie_open() -> None:
    assert evaluate_exit(positie(), price=Decimal("0.80"), moment=START, rules=REGELS) is None


def test_bij_plus_2r_gaat_de_helft_eruit() -> None:
    """2R boven een instap van 1,00 met 1R = 0,25 is 1,50."""
    besluit = evaluate_exit(positie(), price=Decimal("1.50"), moment=START, rules=REGELS)
    assert besluit is not None
    assert besluit.kind is ExitKind.TAKE_HALF
    assert besluit.fraction == Decimal("0.5")


def test_de_winstneming_gebeurt_maar_een_keer() -> None:
    besluit = evaluate_exit(
        positie(half_taken=True, peak_price=Decimal("1.50")),
        price=Decimal("1.60"),
        moment=START,
        rules=REGELS,
    )
    assert besluit is None, "er is geen vaste take-profit; de rest loopt met een trailing stop"


def test_de_trailing_stop_gaat_pas_aan_na_de_helft() -> None:
    """Voor de winstneming is er alleen de harde stop. Zou de trailing stop al eerder
    gelden, dan is de stop niet meer -1R en klopt de sizing niet."""
    diep = positie(peak_price=Decimal("1.40"))
    assert evaluate_exit(diep, price=Decimal("1.00"), moment=START, rules=REGELS) is None


def test_de_trailing_stop_volgt_de_top() -> None:
    na_helft = positie(half_taken=True, peak_price=Decimal("2.00"))
    # 20% onder een top van 2,00 is 1,60.
    assert evaluate_exit(na_helft, price=Decimal("1.70"), moment=START, rules=REGELS) is None
    besluit = evaluate_exit(na_helft, price=Decimal("1.55"), moment=START, rules=REGELS)
    assert besluit is not None
    assert besluit.kind is ExitKind.TRAILING_STOP
    assert besluit.fraction == Decimal("1")


def test_de_stop_weegt_zwaarder_dan_de_winstneming() -> None:
    """Zou een tick die allebei raakt de winst pakken, dan verzin je geld: in werkelijkheid
    weet je niet in welke volgorde het binnen die tick gebeurde, en dan kies je de
    ongunstige kant."""
    besluit = evaluate_exit(positie(), price=Decimal("0.50"), moment=START, rules=REGELS)
    assert besluit is not None and besluit.kind is ExitKind.STOP


def test_een_positie_die_te_lang_openstaat_gaat_eruit() -> None:
    laat = START + timedelta(minutes=REGELS.max_hold_minutes + 1)
    besluit = evaluate_exit(positie(), price=Decimal("1.00"), moment=laat, rules=REGELS)
    assert besluit is not None
    assert besluit.kind is ExitKind.MAX_HOLD
    assert besluit.fraction == Decimal("1")


# --- H0: willekeurig instappen ------------------------------------------------


def kandidaat(minuten_oud: float = 10, pool: str = "pool-1") -> Candidate:
    return Candidate(
        pool_address=pool,
        token_address="token-1",
        venue="synthetic-dex",
        chain="synthetic",
        observed_at=START + timedelta(minutes=minuten_oud),
        price_usd=Decimal("0.001"),
        liquidity_usd=Decimal("50000"),
        volume_usd=Decimal("500"),
        pool_created_at=START,
    )


def test_h0_stapt_alleen_in_tokens_van_de_juiste_leeftijd() -> None:
    """5 tot 30 minuten, net als H1 — anders is het een ander universum."""
    strategie = RandomEntryStrategy(
        seed=1, attempts_per_hour=3600, min_age_minutes=5, max_age_minutes=30
    )
    for minuten, mag in ((1, False), (4.9, False), (5, True), (29, True), (31, False)):
        keuze = strategie.propose(
            moment=START + timedelta(minutes=minuten),
            candidates=[kandidaat(minuten)],
            step_seconds=10,
        )
        assert (keuze is not None) is mag, minuten


def test_h0_is_reproduceerbaar_met_hetzelfde_zaad() -> None:
    """Zonder dit kun je een stresstest niet vergelijken: je zou niet weten of een verschil
    van de stress komt of van het toeval."""

    def keuzes(seed: int) -> list[str | None]:
        strategie = RandomEntryStrategy(
            seed=seed, attempts_per_hour=60, min_age_minutes=5, max_age_minutes=30
        )
        uit = []
        for stap in range(200):
            moment = START + timedelta(minutes=6, seconds=stap * 10)
            keuze = strategie.propose(
                moment=moment,
                candidates=[kandidaat(6, "pool-1"), kandidaat(6, "pool-2")],
                step_seconds=10,
            )
            uit.append(keuze.pool_address if keuze else None)
        return uit

    assert keuzes(7) == keuzes(7)
    assert keuzes(7) != keuzes(8)


def test_h0_probeert_ongeveer_het_opgegeven_aantal_keer_per_uur() -> None:
    """Niet exact — het is kans — maar wel in de buurt, anders is de parameter zinloos."""
    strategie = RandomEntryStrategy(
        seed=3, attempts_per_hour=60, min_age_minutes=0, max_age_minutes=1000
    )
    pogingen = sum(
        1
        for stap in range(360)  # een uur in stappen van tien seconden
        if strategie.propose(
            moment=START + timedelta(seconds=stap * 10),
            candidates=[kandidaat(10)],
            step_seconds=10,
        )
    )
    assert 35 < pogingen < 90, pogingen


def test_h0_kiest_niet_altijd_dezelfde_pool() -> None:
    strategie = RandomEntryStrategy(
        seed=5, attempts_per_hour=3600, min_age_minutes=0, max_age_minutes=1000
    )
    gekozen = set()
    for stap in range(60):
        keuze = strategie.propose(
            moment=START + timedelta(seconds=stap * 10),
            candidates=[kandidaat(10, f"pool-{n}") for n in (1, 2, 3)],
            step_seconds=10,
        )
        if keuze:
            gekozen.add(keuze.pool_address)
    assert len(gekozen) >= 2


# --- De veiligheidsfilters ----------------------------------------------------


def test_wat_niet_te_verifieren_is_wordt_uitgesloten_en_niet_aangenomen() -> None:
    """Sectie 10: tokens waarvan verkoopbaarheid niet te verifiëren is, worden uitgesloten
    en geteld. Niet "waarschijnlijk wel goed"."""
    uitslag = NeverVerifiableOracle().check("pool-1")
    assert uitslag.status is SafetyStatus.UNVERIFIABLE
    assert uitslag.sellable is None
    assert uitslag.unverifiable_filters


def test_de_synthetische_orakel_uitslagen_zijn_reproduceerbaar() -> None:
    eerst = [SyntheticSafetyOracle(seed=2).check(f"pool-{n}").status for n in range(50)]
    nogmaals = [SyntheticSafetyOracle(seed=2).check(f"pool-{n}").status for n in range(50)]
    assert eerst == nogmaals
    assert len(set(eerst)) == 3, "alle drie de uitslagen horen voor te komen"


def test_het_synthetische_orakel_zegt_dat_het_verzonnen_is() -> None:
    uitslag = SyntheticSafetyOracle(seed=1).check("pool-1")
    assert "verzonnen" in uitslag.explanation.lower() or "synthetisch" in uitslag.explanation.lower()


# --- De engine, end-to-end ----------------------------------------------------


async def _corpus(session, **kwargs) -> None:
    from app.services import quant_data_service

    await quant_data_service.record(session, source=bron(**kwargs))
    await session.commit()


async def test_h0_draait_end_to_end_over_een_opgenomen_uur(session) -> None:
    """De acceptatie-eis van fase 3: H0 draait end-to-end over een echt corpus."""
    from app.models.quantlab import QuantPaperTrade, QuantStrategyRun
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session)
    uitslag = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    assert uitslag.ticks > 1000
    assert uitslag.signals_proposed > 0, "H0 heeft niet eens geprobeerd in te stappen"
    assert uitslag.trades_opened > 0, "geen enkele instap kwam door de filters"
    assert uitslag.trades_closed > 0, "geen enkele positie is weer gesloten"

    run = (await session.execute(select(QuantStrategyRun))).scalar_one()
    assert run.variant == "base"
    assert run.trades_closed == uitslag.trades_closed
    # Een resultaat is alleen iets waard tegen een bekend corpus.
    assert len(run.corpus_digest) == 64

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    assert len(trades) == uitslag.trades_opened
    for trade in trades:
        assert trade.entry_reason
        if trade.closed_at is not None:
            assert trade.exit_reason
            assert trade.r_multiple is not None


async def test_elke_trade_bewaart_verwachte_en_gesimuleerde_fill(session) -> None:
    """Sectie 10: elke trade logt verwachte vs. gesimuleerde fill, kosten en de reden."""
    from app.models.quantlab import QuantPaperFill
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session)
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    fills = (await session.execute(select(QuantPaperFill))).scalars().all()
    assert fills
    for fill in fills:
        assert fill.expected_price is not None
        assert fill.latency_ms >= 0
        assert fill.fee_usd >= 0
        if fill.filled:
            assert fill.fill_price > 0
            assert fill.market_price is not None
            assert fill.slippage_usd >= 0
        else:
            assert fill.failure_reason


async def test_niet_genomen_signalen_worden_gelogd_met_een_reden(session) -> None:
    """Tegen cherry-picking: zonder deze log kun je achteraf elke uitkomst mooi praten."""
    from app.models.quantlab import QuantSignal
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session)
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=NeverVerifiableOracle()
    )
    await session.commit()

    signalen = (await session.execute(select(QuantSignal))).scalars().all()
    assert signalen
    assert all(s.taken is False for s in signalen)
    assert all(s.reason == "sellability_unverified" for s in signalen)
    assert all(s.detail for s in signalen)


async def test_een_token_zonder_geverifieerde_verkoopbaarheid_levert_geen_trade(session) -> None:
    from app.services import quant_paper_service

    await _corpus(session)
    uitslag = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=NeverVerifiableOracle()
    )
    await session.commit()

    assert uitslag.signals_proposed > 0
    assert uitslag.trades_opened == 0
    assert uitslag.skipped_by_reason["sellability_unverified"] == uitslag.signals_proposed


async def test_de_risicolaag_blokkeert_ook_in_de_simulatie(session) -> None:
    """De grenzen uit fase 1 gelden ook hier. Een simulatie die ze negeert, meet een
    strategie die in het echt nooit zo had kunnen draaien."""
    from app.services import quant_paper_service

    # Acht pools, want met drie kan er nooit meer dan 3R tegelijk openstaan en komt de
    # 5R-grens niet in zicht. En heel veel pogingen, zodat ze allemaal bezet raken.
    await _corpus(session, pools=8)
    uitslag = await quant_paper_service.run_hypothesis(
        session,
        hypothesis=h0(),
        seed=11,
        safety=AlwaysSafeOracle(),
        attempts_per_hour_override=600,
    )
    await session.commit()

    geweigerd = uitslag.skipped_by_reason.get("risk_veto", 0)
    assert geweigerd > 0, "de risicolaag heeft niets geblokkeerd, en dat kan niet bij 600/uur"
    assert uitslag.max_open_risk_r <= Decimal("5")


async def test_geen_enkele_positie_riskeert_meer_dan_1r(session) -> None:
    from app.models.quantlab import QuantPaperTrade
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session)
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    for trade in trades:
        assert trade.risk_r <= Decimal("1")


async def test_dezelfde_run_twee_keer_geeft_hetzelfde_resultaat(session) -> None:
    from app.services import quant_paper_service

    await _corpus(session)
    eerst = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()
    nogmaals = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    assert eerst.trades_closed == nogmaals.trades_closed
    assert eerst.realized_r == nogmaals.realized_r
    assert eerst.total_fees_usd == nogmaals.total_fees_usd


async def test_een_positie_in_een_stille_pool_gaat_dicht(session) -> None:
    """Zelfde gedachte als de dead-man switch uit fase 1: stilte is geen rust.

    Een pool die doodbloedt, levert geen ticks meer op. Zonder deze regel raakt de positie
    zijn stop nooit — er komt immers geen tick meer om hem op te raken — en wordt hij pas
    aan het eind van het corpus afgerekend, tegen een prijs van uren eerder. Dat was een
    echte fout: trades verloren zo meer dan 1R terwijl de stop op -1R stond."""
    from app.models.quantlab import QuantPaperTrade
    from app.services import quant_data_service, quant_paper_service
    from sqlalchemy import select

    # Pools die na een half uur ophouden, en een corpus dat daarna nog uren doorloopt.
    await quant_data_service.record(
        session,
        source=bron(
            duration=timedelta(hours=4),
            pools=4,
            new_pool_every_minutes=10,
            pool_lifetime_minutes=30,
        ),
    )
    await session.commit()

    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=120,
    )
    await session.commit()

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    assert trades
    redenen = {t.exit_reason for t in trades}
    assert "stale_data" in redenen, f"geen enkele stille pool gesloten; redenen: {redenen}"
    # En het punt waar het om gaat: geen trade verliest meer dan ongeveer 1R.
    for trade in trades:
        if trade.r_multiple is not None:
            assert trade.r_multiple > Decimal("-2"), (
                f"trade {trade.id} verloor {trade.r_multiple}R terwijl de stop op -1R staat"
            )


async def test_geen_enkele_trade_verliest_veel_meer_dan_1r(session) -> None:
    """De harde grens van de hele opzet: de stop staat op -1R.

    Iets meer dan 1R kan: de stop wordt uitgevoerd tegen slippage, en bij een gat in de
    prijs kan de fill lager liggen dan de stop. Veel meer dan 1R betekent dat er iets
    mis is met de sizing of met het sluiten."""
    from app.models.quantlab import QuantPaperTrade
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session, duration=timedelta(hours=6), pools=6,
                  new_pool_every_minutes=5, pool_lifetime_minutes=60)
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=120,
    )
    await session.commit()

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    assert len(trades) > 5, "te weinig trades om hier iets over te zeggen"
    slechtste = min(t.r_multiple for t in trades if t.r_multiple is not None)
    assert slechtste > Decimal("-1.5"), f"slechtste trade was {slechtste}R"


async def test_er_wordt_in_het_handelspad_niets_omgerekend(session) -> None:
    """De papieren rekening staat in dollars, net als de venues.

    Hier zat eerst een omrekening van euro's naar dollars, en die ging de verkeerde kant
    op: vermenigvuldigen met 0,92 in plaats van delen, dus 1000 euro werd 920 dollar in
    plaats van 1087. Op R was dat niet te zien, want 1R en de winst gingen door dezelfde
    koers en de fout viel weg. Wat er wel misging: de positie was 15% te klein, dus het
    filter "liquiditeit minstens 50x de positie" stond te ruim en de slippage viel te laag
    uit — precies het soort fout dat zich verstopt achter een getal dat klopt.

    De oplossing is niet een betere omrekening maar géén omrekening. Deze test pint dat
    vast: wat erin gaat, komt er onveranderd uit."""
    from app.models.quantlab import QuantStrategyRun
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(session, duration=timedelta(minutes=30))
    await quant_paper_service.run_hypothesis(
        session,
        hypothesis=h0(),
        seed=1,
        safety=AlwaysSafeOracle(),
        equity_usd=Decimal("1000"),
    )
    await session.commit()

    run = (await session.execute(select(QuantStrategyRun))).scalar_one()
    assert run.equity_quote == Decimal("1000.00")
    # 1R is 0,75% van de equity: 7,50 dollar.
    assert run.one_r_quote == Decimal("7.50")


async def test_de_stop_is_per_trade_anders(session) -> None:
    """Het punt van de hele wijziging: niet één percentage voor alles.

    Elke trade legt vast waar zijn stop vandaan kwam, want zonder dat kun je achteraf niet
    nagaan waarom een positie zo groot was."""
    from app.models.quantlab import QuantPaperTrade
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(
        session, duration=timedelta(hours=4), pools=6,
        new_pool_every_minutes=5, pool_lifetime_minutes=60,
    )
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0_v2(), seed=11, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=120,
    )
    await session.commit()

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    assert len(trades) > 5
    afstanden = {t.stop_distance_pct for t in trades}
    assert len(afstanden) > 1, f"elke trade kreeg dezelfde stop: {afstanden}"
    for trade in trades:
        assert trade.stop_basis, "geen uitleg waar de stop vandaan kwam"
        assert Decimal("0.20") <= trade.stop_distance_pct <= Decimal("0.50")


async def test_de_stopgrenzen_worden_niet_overschreden(session) -> None:
    """De ondergrens van 20% is afgeleid uit het kostenmodel; eronder eet de slippage je
    1R op. De bovengrens houdt tegen dat de helft pas bij een verdubbeling eruit gaat."""
    from app.models.quantlab import QuantPaperTrade
    from app.services import quant_paper_service
    from sqlalchemy import select

    await _corpus(
        session, duration=timedelta(hours=3), pools=8,
        new_pool_every_minutes=5, pool_lifetime_minutes=60,
    )
    await quant_paper_service.run_hypothesis(
        session, hypothesis=h0_v2(), seed=3, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=200,
    )
    await session.commit()

    trades = (await session.execute(select(QuantPaperTrade))).scalars().all()
    assert trades
    for trade in trades:
        assert trade.stop_distance_pct >= Decimal("0.20")
        assert trade.stop_distance_pct <= Decimal("0.50")
        assert trade.stop_price < trade.entry_fill_price


async def test_een_vaste_en_een_structurele_stop_zijn_te_vergelijken(session) -> None:
    """Een structurele stop is alleen beter als je kunt laten zien dát hij beter is.

    Daarom blijft de vaste vorm bestaan en draaien ze over hetzelfde corpus met hetzelfde
    zaad: dan proberen ze dezelfde instappen en is het enige verschil de stop."""
    from app.services import quant_paper_service

    await _corpus(
        session, duration=timedelta(hours=4), pools=6,
        new_pool_every_minutes=5, pool_lifetime_minutes=60,
    )
    vast = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=120,
    )
    await session.commit()
    structureel = await quant_paper_service.run_hypothesis(
        session, hypothesis=h0_v2(), seed=11, safety=AlwaysSafeOracle(),
        attempts_per_hour_override=120,
    )
    await session.commit()

    assert vast.signals_proposed == structureel.signals_proposed
    assert vast.trades_opened > 0 and structureel.trades_opened > 0


# --- De stresstest ------------------------------------------------------------


async def test_de_stresstest_draait_vier_varianten(session) -> None:
    from app.services import quant_paper_service

    await _corpus(session)
    uitslagen = await quant_paper_service.run_stress_suite(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    assert set(uitslagen) == set(STRESS_PROFILES)
    for naam, uitslag in uitslagen.items():
        assert uitslag.variant == naam
        assert uitslag.ticks > 0


async def test_de_varianten_proberen_dezelfde_instappen(session) -> None:
    """Het enige verschil tussen de varianten mag het fill-model zijn. Zouden de instappen
    ook verschillen, dan vergelijk je twee strategieën in plaats van twee werelden."""
    from app.services import quant_paper_service

    await _corpus(session)
    uitslagen = await quant_paper_service.run_stress_suite(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    aantallen = {u.signals_proposed for u in uitslagen.values()}
    assert len(aantallen) == 1, f"de varianten probeerden verschillende instappen: {aantallen}"


async def test_tweemaal_slippage_kost_meer_slippage(session) -> None:
    from app.services import quant_paper_service

    await _corpus(session)
    uitslagen = await quant_paper_service.run_stress_suite(
        session, hypothesis=h0(), seed=11, safety=AlwaysSafeOracle()
    )
    await session.commit()

    basis = uitslagen["base"]
    zwaar = uitslagen["slippage_2x"]
    assert zwaar.total_slippage_usd > basis.total_slippage_usd


# --- Metrics ------------------------------------------------------------------


def resultaten(*waarden: str) -> list[TradeResult]:
    return [TradeResult(r_multiple=Decimal(w)) for w in waarden]


def test_expectancy_komt_met_een_betrouwbaarheidsinterval() -> None:
    """Cultuurregel: geen enkele claim zonder N, kosten en onzekerheidsmarge."""
    uitslag = expectancy(resultaten("1", "-1", "2", "-1", "1", "-1"), seed=1)
    assert uitslag.n == 6
    assert uitslag.expectancy_r == Decimal("0.1667")
    assert uitslag.ci_low < uitslag.expectancy_r < uitslag.ci_high
    assert uitslag.confidence == Decimal("0.90")


def test_onder_150_trades_is_de_conclusie_te_vroeg() -> None:
    """Sectie 8: pas bij N >= 150 conclusies; eerder alleen "te vroeg"."""
    uitslag = expectancy(resultaten(*["1"] * 20), seed=1, min_trades=150)
    assert uitslag.conclusion_allowed is False
    assert "te vroeg" in uitslag.verdict.lower()

    genoeg = expectancy(resultaten(*(["1", "-1"] * 80)), seed=1, min_trades=150)
    assert genoeg.n == 160
    assert genoeg.conclusion_allowed is True


def test_zonder_trades_is_er_geen_expectancy() -> None:
    uitslag = expectancy([], seed=1)
    assert uitslag.n == 0
    assert uitslag.expectancy_r is None
    assert "geen" in uitslag.verdict.lower()


def test_de_maximale_drawdown_wordt_in_r_gemeten() -> None:
    # Loopt op naar +3R, zakt naar -1R: dat is een drawdown van 4R.
    assert max_drawdown_r(resultaten("1", "1", "1", "-2", "-2")) == Decimal("4")
    assert max_drawdown_r(resultaten("1", "1")) == Decimal("0")
    assert max_drawdown_r([]) == Decimal("0")


# --- Over HTTP ---------------------------------------------------------------


async def test_de_hypotheses_en_runs_zijn_zichtbaar_vanaf_tier_2(
    client, trusted, session
) -> None:
    from app.services import quant_paper_service
    from tests.conftest import auth_headers

    await quant_paper_service.register_hypothesis(session, h0())
    await session.commit()

    hypotheses = await client.get("/quant/hypotheses", headers=auth_headers(trusted))
    assert hypotheses.status_code == 200, hypotheses.text
    body = hypotheses.json()
    assert body[0]["name"] == "H0"
    assert body[0]["paper_only"] is True
    assert len(body[0]["content_hash"]) == 64

    for pad in ("/quant/paper/runs", "/quant/paper/trades"):
        antwoord = await client.get(pad, headers=auth_headers(trusted))
        assert antwoord.status_code == 200, pad


async def test_een_gast_mag_de_papieren_handel_niet_zien(client, session) -> None:
    from app.core.security import hash_password
    from app.models.user import TIER_GUEST, User
    from tests.conftest import auth_headers

    gast = User(
        email="gast-paper@example.com",
        display_name="Gast",
        password_hash=hash_password("geheim123"),
        tier=TIER_GUEST,
    )
    session.add(gast)
    await session.commit()

    for pad in ("/quant/hypotheses", "/quant/paper/runs", "/quant/paper/trades"):
        assert (await client.get(pad, headers=auth_headers(gast))).status_code == 403, pad
