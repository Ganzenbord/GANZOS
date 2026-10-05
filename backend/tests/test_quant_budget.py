"""Het kostenledger en de budget governor (sectie 12), plus de LLM-off modus.

Ook deze tests staan er vóór de code. De reden is dezelfde als bij de risicolaag: een
budget dat pas opvalt als de rekening komt, is geen budget. De acceptatie-eis van fase 1
staat onderaan dit bestand: met een gesimuleerd leeg budget moet het lab blijven draaien
op `RulesOnly`, en het resultaat moet als `degraded` gemarkeerd zijn.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from app.quantlab import budget_limits
from app.quantlab.agents import QuantAgent
from app.quantlab.budget import (
    BudgetMode,
    BudgetVeto,
    BudgetVerdict,
    SpendSnapshot,
    VETO_UITLEG,
    daily_cap_eur,
    evaluate_call,
)
from app.quantlab.decision import (
    SHADOW_DECISIONS_REQUIRED,
    DecisionInput,
    DecisionOutput,
    GuardedDecisionModel,
    RulesOnly,
    ShadowDecisionModel,
)
from app.quantlab.pricing import (
    PRICES,
    TokenUsage,
    UnknownModelPrice,
    cost_eur,
    cost_usd,
)

OPDRACHT = DecisionInput(hypothesis="H1_v1", features={"liquidity_usd": 50000.0})


def leeg(month: Decimal = Decimal("0"), **per_agent: Decimal) -> SpendSnapshot:
    """Een stand van de uitgaven, standaard alles op nul."""
    maand = {agent: per_agent.get(agent.value, Decimal("0")) for agent in QuantAgent}
    return SpendSnapshot(
        day=date(2026, 10, 7),
        month_total_eur=month,
        month_per_agent_eur=maand,
        day_per_agent_eur={agent: Decimal("0") for agent in QuantAgent},
    )


# --- De startverdeling uit de opdracht ---------------------------------------


def test_de_startverdeling_staat_er_letterlijk() -> None:
    budgetten = budget_limits.AGENT_MONTHLY_BUDGET_EUR
    assert budgetten[QuantAgent.REVIEWER] == Decimal("70")
    assert budgetten[QuantAgent.ANALYST] == Decimal("50")
    assert budgetten[QuantAgent.CLASSIFIER] == Decimal("10")
    assert budget_limits.RESERVE_EUR == Decimal("70")


def test_de_verdeling_telt_op_tot_het_maandplafond() -> None:
    """Een verdeling die niet optelt, is een plafond dat niet klopt."""
    verdeeld = sum(budget_limits.AGENT_MONTHLY_BUDGET_EUR.values())
    assert verdeeld + budget_limits.RESERVE_EUR == budget_limits.MONTHLY_HARD_CAP_EUR
    assert budget_limits.MONTHLY_HARD_CAP_EUR == Decimal("200")
    assert budget_limits.MONTHLY_WARNING_EUR == Decimal("150")


def test_agents_van_pure_code_hebben_geen_budget() -> None:
    """Scout, Screener en Risk Officer zijn code. Code die een model aanroept, is geen code
    meer — en de Risk Officer mag al helemaal nooit van een antwoord afhangen."""
    for agent in (QuantAgent.SCOUT, QuantAgent.SCREENER, QuantAgent.RISK_OFFICER):
        assert agent not in budget_limits.AGENT_MONTHLY_BUDGET_EUR


def test_de_daggrens_is_twee_keer_het_deel_van_die_dag() -> None:
    """Een dag mag hoogstens het dubbele van zijn pro-rata deel gebruiken, zodat één
    doorgedraaide dag niet de hele maand opeet. Oktober heeft 31 dagen: 70 / 31 x 2."""
    assert daily_cap_eur(QuantAgent.REVIEWER, date(2026, 10, 7)) == Decimal("4.51")
    assert daily_cap_eur(QuantAgent.CLASSIFIER, date(2026, 10, 7)) == Decimal("0.64")
    # Februari is korter, dus mag een dag daar iets meer.
    assert daily_cap_eur(QuantAgent.REVIEWER, date(2026, 2, 7)) == Decimal("5.00")


def test_een_agent_zonder_budget_heeft_ook_geen_daggrens() -> None:
    assert daily_cap_eur(QuantAgent.RISK_OFFICER, date(2026, 10, 7)) == Decimal("0")


# --- Prijzen ------------------------------------------------------------------


def test_elke_prijs_heeft_een_bron_en_een_datum() -> None:
    """Sectie 12: prijzen komen uit de officiële documentatie, niet uit het hoofd.

    Een prijs zonder bron is een gok, en een gok in een budget is een rekening."""
    assert PRICES, "er staat geen enkel model in de prijslijst"
    for model, prijs in PRICES.items():
        assert prijs.source.startswith("https://"), model
        assert prijs.verified_on <= date.today(), model
        assert prijs.input_usd_per_mtok > 0, model
        assert prijs.output_usd_per_mtok > 0, model


def test_de_kosten_van_een_aanroep_in_dollars() -> None:
    """Haiku 4.5: 1 dollar per miljoen in, 5 per miljoen uit."""
    kosten = cost_usd(
        "claude-haiku-4-5", TokenUsage(input_tokens=1_000_000, output_tokens=100_000)
    )
    assert kosten == Decimal("1.500000")


def test_een_cachetreffer_is_tien_keer_goedkoper() -> None:
    vol = cost_usd("claude-haiku-4-5", TokenUsage(input_tokens=1_000_000))
    uit_cache = cost_usd(
        "claude-haiku-4-5", TokenUsage(input_tokens=0, cache_read_tokens=1_000_000)
    )
    assert vol == Decimal("1.000000")
    assert uit_cache == Decimal("0.100000")


def test_de_reviewer_is_duur() -> None:
    """Fable 5.1 kost tien keer zoveel per token als Haiku. Dat staat hier zodat een
    verkeerd modelnaampje in de code meteen opvalt in de prijs."""
    assert cost_usd("claude-fable-5-1", TokenUsage(input_tokens=1_000_000)) == Decimal(
        "10.000000"
    )


def test_een_onbekend_model_wordt_niet_geraden() -> None:
    """Nul euro boeken voor een aanroep die wel geld kost, is erger dan weigeren."""
    with pytest.raises(UnknownModelPrice):
        cost_usd("claude-magisch-9", TokenUsage(input_tokens=1000))


def test_jev_staat_nog_niet_in_de_prijslijst() -> None:
    """We willen JEV.ai gebruiken, maar wat het kost is hier niet te verifiëren.

    Zolang de prijs er niet staat, kan een JEV-aanroep niet geboekt worden en dus ook niet
    draaien. Dat is de bedoeling: liever een duidelijke fout dan een ongemeten rekening.
    Zie de openstaande vraag in het fase 1-rapport."""
    assert not any("jev" in model.lower() for model in PRICES)
    with pytest.raises(UnknownModelPrice) as fout:
        cost_usd("jev-classifier", TokenUsage(input_tokens=1000))
    assert "prijs" in str(fout.value).lower()


def test_kleine_bedragen_vallen_niet_weg_in_de_afronding() -> None:
    """Een aanroep van een halve cent moet in het boek blijven staan.

    Afronden op centen per aanroep zou betekenen dat duizend kleine aanroepen samen nul
    euro kosten. Daarom rekent het boek met zes decimalen."""
    klein = cost_eur(
        "claude-haiku-4-5", TokenUsage(input_tokens=1000), rate=Decimal("0.92")
    )
    assert klein > 0
    assert klein == Decimal("0.000920")


# --- De budget governor -------------------------------------------------------


def test_een_gewone_aanroep_mag() -> None:
    besluit = evaluate_call(leeg(), QuantAgent.ANALYST, Decimal("0.01"))
    assert besluit.allowed is True
    assert besluit.mode is BudgetMode.NORMAL
    assert besluit.veto is None


def test_boven_150_euro_waarschuwt_het_budget_maar_gaat_door() -> None:
    besluit = evaluate_call(leeg(month=Decimal("151")), QuantAgent.ANALYST, Decimal("0.01"))
    assert besluit.allowed is True
    assert besluit.mode is BudgetMode.WARNING


def test_op_200_euro_gaan_de_taalmodellen_uit() -> None:
    besluit = evaluate_call(leeg(month=Decimal("200")), QuantAgent.ANALYST, Decimal("0.01"))
    assert besluit.allowed is False
    assert besluit.mode is BudgetMode.LLM_OFF
    assert besluit.veto is BudgetVeto.MONTH_CAP_REACHED


def test_een_aanroep_die_het_plafond_zou_doorbreken_gaat_niet_door() -> None:
    """Niet "tot het plafond en dan stoppen" maar "nooit erover": de aanroep die eroverheen
    zou gaan, gaat niet."""
    besluit = evaluate_call(
        leeg(month=Decimal("199.99")), QuantAgent.REVIEWER, Decimal("1.00")
    )
    assert besluit.allowed is False
    assert besluit.mode is BudgetMode.LLM_OFF


def test_de_reserve_is_niet_automatisch_beschikbaar() -> None:
    """De Reviewer heeft 70 euro. Is die op, dan stopt de Reviewer — ook al is er van de
    200 euro nog 130 over. Die 70 euro reserve is van Stef, niet van een agent."""
    stand = leeg(month=Decimal("70"), reviewer=Decimal("70"))
    besluit = evaluate_call(stand, QuantAgent.REVIEWER, Decimal("0.50"))
    assert besluit.allowed is False
    assert besluit.veto is BudgetVeto.AGENT_MONTH_CAP_REACHED
    # Het lab als geheel is niet uit: een andere agent mag nog.
    assert besluit.mode is BudgetMode.NORMAL
    assert evaluate_call(stand, QuantAgent.ANALYST, Decimal("0.50")).allowed is True


def test_de_daggrens_houdt_een_doorgedraaide_agent_tegen() -> None:
    stand = SpendSnapshot(
        day=date(2026, 10, 7),
        month_total_eur=Decimal("5"),
        month_per_agent_eur={QuantAgent.REVIEWER: Decimal("5")},
        day_per_agent_eur={QuantAgent.REVIEWER: Decimal("4.50")},
    )
    besluit = evaluate_call(stand, QuantAgent.REVIEWER, Decimal("0.50"))
    assert besluit.allowed is False
    assert besluit.veto is BudgetVeto.AGENT_DAY_CAP_REACHED


def test_een_agent_van_pure_code_mag_geen_cent_uitgeven() -> None:
    besluit = evaluate_call(leeg(), QuantAgent.RISK_OFFICER, Decimal("0.01"))
    assert besluit.allowed is False
    assert besluit.veto is BudgetVeto.AGENT_WITHOUT_BUDGET


def test_elke_weigering_heeft_een_uitleg_in_gewone_taal() -> None:
    for veto in BudgetVeto:
        assert len(VETO_UITLEG[veto]) > 20, veto


# --- Het kostenboek in de database -------------------------------------------


async def test_elke_aanroep_komt_in_het_kostenboek(session) -> None:
    from app.models.quantlab import QuantLlmCall
    from app.services import quant_cost_service
    from sqlalchemy import select

    await quant_cost_service.book_call(
        session,
        agent=QuantAgent.REVIEWER,
        model="claude-fable-5-1",
        usage=TokenUsage(input_tokens=60_000, output_tokens=4_000),
        purpose="dagrapport",
        rate=Decimal("0.92"),
    )
    await session.commit()

    rij = (await session.execute(select(QuantLlmCall))).scalar_one()
    assert rij.agent == QuantAgent.REVIEWER.value
    assert rij.model == "claude-fable-5-1"
    assert rij.input_tokens == 60_000
    assert rij.output_tokens == 4_000
    # 60k in à 10 dollar + 4k uit à 50 dollar = 0,60 + 0,20 = 0,80 dollar.
    assert rij.cost_usd == Decimal("0.800000")
    assert rij.cost_eur == Decimal("0.736000")
    assert rij.fx_rate == Decimal("0.92")


async def test_een_aanroep_op_een_onbekend_model_wordt_niet_geboekt(session) -> None:
    from app.models.quantlab import QuantLlmCall
    from app.services import quant_cost_service
    from sqlalchemy import select

    with pytest.raises(UnknownModelPrice):
        await quant_cost_service.book_call(
            session,
            agent=QuantAgent.CLASSIFIER,
            model="jev-classifier",
            usage=TokenUsage(input_tokens=100),
            purpose="score",
            rate=Decimal("0.92"),
        )
    assert (await session.execute(select(QuantLlmCall))).scalars().all() == []


async def test_het_kostenboek_rekent_per_maand_en_per_dag(session) -> None:
    from app.models.quantlab import QuantLlmCall
    from app.services import quant_cost_service

    nu = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    vorige_maand = datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc)
    gisteren = nu - timedelta(days=1)
    for tijd, eur in ((vorige_maand, "9"), (gisteren, "2"), (nu, "1")):
        session.add(
            QuantLlmCall(
                agent=QuantAgent.ANALYST.value,
                model="claude-haiku-4-5",
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                cost_usd=Decimal(eur),
                cost_eur=Decimal(eur),
                fx_rate=Decimal("1"),
                purpose="test",
                created_at=tijd,
            )
        )
    await session.commit()

    stand = await quant_cost_service.spend_snapshot(session, now=nu)
    assert stand.month_total_eur == Decimal("3")
    assert stand.month_per_agent_eur[QuantAgent.ANALYST] == Decimal("3")
    assert stand.day_per_agent_eur[QuantAgent.ANALYST] == Decimal("1")


# --- RulesOnly en de LLM-off modus -------------------------------------------


async def test_regels_zonder_taalmodel_werken_altijd() -> None:
    """`RulesOnly` is de standaard en is er altijd: geen budget, geen netwerk, geen sleutel."""
    model = RulesOnly()
    uitslag = await model.decide(OPDRACHT)
    assert isinstance(uitslag, DecisionOutput)
    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is False
    assert 0.0 <= uitslag.score <= 1.0


class TraagModel:
    """Een model dat niet op tijd antwoordt."""

    name = "traag"
    agent = QuantAgent.CLASSIFIER
    estimated_eur = Decimal("0.001")

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        await asyncio.sleep(5)
        raise AssertionError("had nooit zo lang mogen duren")


class KapotModel:
    """Een model dat iets teruggeeft wat niet in het schema past."""

    name = "kapot"
    agent = QuantAgent.CLASSIFIER
    estimated_eur = Decimal("0.001")

    def __init__(self, score: float) -> None:
        self._score = score

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        return DecisionOutput(
            score=self._score, model_name="kapot", degraded=False, reason="ik weet het zeker"
        )


class GoedModel:
    name = "goed"
    agent = QuantAgent.CLASSIFIER
    estimated_eur = Decimal("0.001")

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        return DecisionOutput(score=0.8, model_name="goed", degraded=False, reason="ok")


def budget_vol() -> BudgetVerdict:
    return BudgetVerdict(
        allowed=False,
        mode=BudgetMode.LLM_OFF,
        veto=BudgetVeto.MONTH_CAP_REACHED,
        reason=VETO_UITLEG[BudgetVeto.MONTH_CAP_REACHED],
        estimated_eur=Decimal("0.001"),
        month_total_eur=Decimal("200"),
        month_remaining_eur=Decimal("0"),
    )


def budget_ruimte() -> BudgetVerdict:
    return BudgetVerdict(
        allowed=True,
        mode=BudgetMode.NORMAL,
        veto=None,
        reason="",
        estimated_eur=Decimal("0.001"),
        month_total_eur=Decimal("0"),
        month_remaining_eur=Decimal("200"),
    )


async def test_met_een_leeg_budget_valt_het_lab_terug_op_de_regels() -> None:
    """De acceptatie-eis van fase 1: een gesimuleerd leeg budget zet de modellen uit, en het
    lab draait door op `RulesOnly` — gemarkeerd als `degraded`."""
    gevraagd: list[QuantAgent] = []

    async def controleer(agent: QuantAgent, eur: Decimal) -> BudgetVerdict:
        gevraagd.append(agent)
        return budget_vol()

    model = GuardedDecisionModel(GoedModel(), budget_check=controleer)
    uitslag = await model.decide(OPDRACHT)

    assert gevraagd == [QuantAgent.CLASSIFIER]
    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is True
    assert "budget" in uitslag.reason.lower()
    assert model.budget_blocked == 1


async def test_met_ruimte_in_het_budget_draait_het_model_zelf() -> None:
    async def controleer(agent: QuantAgent, eur: Decimal) -> BudgetVerdict:
        return budget_ruimte()

    model = GuardedDecisionModel(GoedModel(), budget_check=controleer)
    uitslag = await model.decide(OPDRACHT)
    assert uitslag.model_name == "goed"
    assert uitslag.degraded is False
    assert model.budget_blocked == 0


async def test_een_model_dat_te_lang_nadenkt_valt_terug_op_de_regels() -> None:
    async def controleer(agent: QuantAgent, eur: Decimal) -> BudgetVerdict:
        return budget_ruimte()

    model = GuardedDecisionModel(
        TraagModel(), budget_check=controleer, timeout_seconds=0.05
    )
    uitslag = await model.decide(OPDRACHT)
    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is True
    assert model.timeouts == 1


@pytest.mark.parametrize("score", [1.7, -0.2, float("nan"), float("inf")])
async def test_een_antwoord_buiten_het_schema_wordt_weggegooid_en_geteld(score: float) -> None:
    """Sectie 10: een antwoord dat niet in het schema past, wordt niet gerepareerd.

    Van 1,7 een 1,0 maken is het ergste wat je kunt doen: dan ziet niemand ooit dat het
    model iets anders zei dan afgesproken."""

    async def controleer(agent: QuantAgent, eur: Decimal) -> BudgetVerdict:
        return budget_ruimte()

    model = GuardedDecisionModel(KapotModel(score), budget_check=controleer)
    uitslag = await model.decide(OPDRACHT)

    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is True
    assert model.discarded == 1
    assert uitslag.score != score


async def test_een_model_dat_klapt_haalt_het_lab_niet_onderuit() -> None:
    class KlapModel(GoedModel):
        async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
            raise RuntimeError("verbinding weg")

    async def controleer(agent: QuantAgent, eur: Decimal) -> BudgetVerdict:
        return budget_ruimte()

    model = GuardedDecisionModel(KlapModel(), budget_check=controleer)
    uitslag = await model.decide(OPDRACHT)
    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is True
    assert model.failures == 1


async def test_het_echte_budget_met_een_volgeboekte_maand(session) -> None:
    """Dezelfde terugval, nu met de echte governor en een maand die vol staat in het boek."""
    from app.models.quantlab import QuantLlmCall
    from app.services import quant_cost_service

    nu = datetime.now(timezone.utc)
    session.add(
        QuantLlmCall(
            agent=QuantAgent.REVIEWER.value,
            model="claude-fable-5-1",
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_usd=Decimal("200"),
            cost_eur=Decimal("200"),
            fx_rate=Decimal("1"),
            purpose="gesimuleerd leeg budget",
            created_at=nu,
        )
    )
    await session.commit()

    governor = quant_cost_service.BudgetGovernor(session, now=nu)
    model = GuardedDecisionModel(GoedModel(), budget_check=governor.may_call)
    uitslag = await model.decide(OPDRACHT)

    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is True

    status = await quant_cost_service.budget_status(session, now=nu)
    assert status.mode is BudgetMode.LLM_OFF
    assert status.month_total_eur == Decimal("200")


# --- Schaduwmodus voor JEV ----------------------------------------------------


def test_de_schaduwmodus_duurt_honderd_beslissingen() -> None:
    """Sectie 7: JEV draait de eerste 100 beslissingen mee zonder iets te bepalen."""
    assert SHADOW_DECISIONS_REQUIRED == 100


async def test_in_de_schaduw_bepaalt_het_nieuwe_model_niets() -> None:
    gelogd: list[tuple[str, float | None]] = []

    async def log(naam: str, score: float | None) -> None:
        gelogd.append((naam, score))

    model = ShadowDecisionModel(
        used=RulesOnly(), shadow=GoedModel(), on_result=log
    )
    uitslag = await model.decide(OPDRACHT)

    assert uitslag.model_name == "rules_only"
    assert ("goed", 0.8) in gelogd


async def test_een_schaduwmodel_dat_klapt_verandert_niets_aan_het_besluit() -> None:
    class KlapModel(GoedModel):
        async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
            raise RuntimeError("JEV is onbereikbaar")

    gelogd: list[tuple[str, float | None]] = []

    async def log(naam: str, score: float | None) -> None:
        gelogd.append((naam, score))

    model = ShadowDecisionModel(used=RulesOnly(), shadow=KlapModel(), on_result=log)
    uitslag = await model.decide(OPDRACHT)

    assert uitslag.model_name == "rules_only"
    assert uitslag.degraded is False
    assert gelogd == [("goed", None)]


# --- Over HTTP ---------------------------------------------------------------


async def test_het_kostenoverzicht_is_alleen_voor_de_eigenaar(client, owner, trusted) -> None:
    from tests.conftest import auth_headers

    assert (await client.get("/quant/costs", headers=auth_headers(trusted))).status_code == 403

    antwoord = await client.get("/quant/costs", headers=auth_headers(owner))
    assert antwoord.status_code == 200, antwoord.text
    body = antwoord.json()
    assert body["mode"] == BudgetMode.NORMAL.value
    assert body["monthly_cap_eur"] == "200"
    agenten = {regel["agent"]: regel for regel in body["agents"]}
    assert agenten["reviewer"]["monthly_budget_eur"] == "70"
