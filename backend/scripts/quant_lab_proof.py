"""Laat zien dat de risicolaag en het budget werken, met echte rijen uit de database.

De testsuite bewijst hetzelfde, maar een test is iets wat je moet vertrouwen. Dit script
draait een paar bewuste overtredingen tegen een echte PostgreSQL en drukt af wat er in de
tabellen terechtkomt, zodat je het zelf kunt nakijken.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \\
      python -m scripts.quant_lab_proof

Het script schrijft rijen. Draai hem dus op een proefdatabase, niet op de echte — in
productie weigert hij.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.database import Database
from app.models.quantlab import (
    QuantHeartbeat,
    QuantLlmCall,
    QuantRiskBooking,
    QuantRiskControl,
    QuantRiskEvent,
)
from app.quantlab.agents import QuantAgent
from app.quantlab.budget import BudgetMode
from app.quantlab.decision import DecisionInput, GuardedDecisionModel, RulesOnly
from app.quantlab.pricing import TokenUsage, cost_eur
from app.quantlab.risk import EntryRequest
from app.services import quant_cost_service, quant_risk_service

EQUITY = Decimal("10000")
# Woensdag midden in de week: zo kan een weekverlies van maandag de dagstop ongemoeid laten.
NU = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MAANDAG = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)

INSTAP = EntryRequest(
    hypothesis="H1_v1", entry_price=Decimal("1.00"), stop_price=Decimal("0.90")
)


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}")


async def leegmaken(session) -> None:
    """Alleen de tabellen van het lab, zodat de uitkomst elke keer hetzelfde is."""
    for tabel in (QuantRiskEvent, QuantRiskControl, QuantRiskBooking, QuantHeartbeat, QuantLlmCall):
        await session.execute(delete(tabel))
    await session.commit()


async def risico(session) -> None:
    kop("1. De risicolaag: acht pogingen, waarvan zeven bewuste overtredingen")

    async def poging(naam: str, *, request=INSTAP, open_risk=Decimal("0")) -> None:
        besluit = await quant_risk_service.check_entry(
            session, equity=EQUITY, request=request, open_risk_r=open_risk, now=NU
        )
        await session.commit()
        stand = "TOEGESTAAN" if besluit.allowed else f"GEBLOKKEERD ({besluit.veto.value})"
        print(f"  {naam:<34} {stand}")

    # Zonder hartslag houdt de dead-man switch alles tegen; dat is de eerste poging.
    await poging("geen hartslag")

    await quant_risk_service.heartbeat(session, component="scout", now=NU)
    await session.commit()
    await poging("gezonde stand")
    await poging(
        "1,5R gevraagd",
        request=EntryRequest(
            hypothesis="H1_v1",
            entry_price=Decimal("1.00"),
            stop_price=Decimal("0.90"),
            risk_r=Decimal("1.5"),
        ),
    )
    await poging("al 5R open", open_risk=Decimal("5"))
    await poging(
        "stop op de instapprijs",
        request=EntryRequest(
            hypothesis="H1_v1", entry_price=Decimal("1.00"), stop_price=Decimal("1.00")
        ),
    )

    session.add(
        QuantRiskBooking(
            hypothesis="H1_v1", r_multiple=Decimal("-3"), closed_at=NU, note="dagverlies"
        )
    )
    await session.commit()
    await poging("-3R vandaag")

    session.add(
        QuantRiskBooking(
            hypothesis="H1_v1", r_multiple=Decimal("-5"), closed_at=MAANDAG, note="weekverlies"
        )
    )
    await session.commit()
    await poging("-8R deze week")

    await quant_risk_service.reset_week_stop(
        session, user_id=None, reason="proef: Stef kijkt mee", now=NU
    )
    await session.commit()
    stand = await quant_risk_service.snapshot(session, equity=EQUITY, now=NU)
    print(
        f"  na een handmatige weekreset        weekgrens staat nu op {stand.week_stop_level_r}R "
        f"(weekstand {stand.realized_week_r}R)"
    )

    await quant_risk_service.engage_kill_switch(
        session, reason="proef", source="user", user_id=None
    )
    await session.commit()
    await poging("noodstop aan")

    kop("2. Wat er in quant_risk_events staat")
    rijen = await session.execute(
        select(QuantRiskEvent.allowed, QuantRiskEvent.veto, func.count())
        .group_by(QuantRiskEvent.allowed, QuantRiskEvent.veto)
        .order_by(func.count().desc())
    )
    print(f"  {'toegestaan':<12}{'veto':<28}aantal")
    for toegestaan, veto, aantal in rijen.all():
        print(f"  {str(toegestaan):<12}{veto or '-':<28}{aantal}")


async def kosten(session) -> None:
    kop("3. Het kostenboek: van normaal naar leeg")

    async def aanroep(agent: QuantAgent, model: str, usage: TokenUsage) -> None:
        # De schatting vooraf is hier de werkelijke prijs van dit verbruik. In het lab zelf
        # is het een schatting die eerder te hoog dan te laag hoort te zijn.
        schatting = cost_eur(model, usage, rate=quant_cost_service.DEFAULT_USD_EUR_RATE)
        verdict = await quant_cost_service.BudgetGovernor(session, now=NU).may_call(
            agent, schatting
        )
        if not verdict.allowed:
            print(f"  {agent.value:<12} geweigerd: {verdict.veto.value}")
            return
        rij = await quant_cost_service.book_call(
            session, agent=agent, model=model, usage=usage, purpose="proef", now=NU
        )
        await session.commit()
        print(f"  {agent.value:<12} geboekt: ${rij.cost_usd} = EUR {rij.cost_eur}")

    await aanroep(
        QuantAgent.REVIEWER,
        "claude-fable-5-1",
        TokenUsage(input_tokens=60_000, output_tokens=4_000),
    )
    await aanroep(
        QuantAgent.CLASSIFIER, "claude-haiku-4-5", TokenUsage(input_tokens=2_000)
    )
    await aanroep(QuantAgent.RISK_OFFICER, "claude-haiku-4-5", TokenUsage(input_tokens=10))

    stand = await quant_cost_service.budget_status(session, now=NU)
    print(f"\n  stand: {stand.mode.value} — deze maand EUR {stand.month_total_eur} van "
          f"EUR {stand.monthly_cap_eur}")
    for regel in stand.agents:
        print(
            f"    {regel.agent.value:<12} maand EUR {regel.month_spent_eur} van "
            f"{regel.monthly_budget_eur}, dag EUR {regel.day_spent_eur} van "
            f"{regel.daily_cap_eur}"
        )

    kop("4. Drie standen: normaal, waarschuwing, en budget op")

    async def kunstmatig(bedrag: str, waarom: str) -> None:
        """Een geboekte post om een stand te bereiken zonder er echt geld aan te geven."""
        session.add(
            QuantLlmCall(
                agent=QuantAgent.REVIEWER.value,
                model="claude-fable-5-1",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cost_usd=Decimal(bedrag),
                cost_eur=Decimal(bedrag),
                fx_rate=Decimal("1"),
                purpose=waarom,
                created_at=NU,
            )
        )
        await session.commit()
        stand = await quant_cost_service.budget_status(session, now=NU)
        print(f"  EUR {stand.month_total_eur:>12} deze maand -> {stand.mode.value}")

    await kunstmatig("150", "proef: waarschuwingsgrens")
    await kunstmatig("50", "proef: budget vol")

    kop("5. Een leeg budget: het lab draait door op de regels")

    # Het budget staat na stap 4 al op 200 euro; hier wordt niets bijgeboekt.
    class NooitAangeroepen:
        name = "classifier"
        agent = QuantAgent.CLASSIFIER
        estimated_eur = Decimal("0.001")

        async def decide(self, opdracht: DecisionInput):
            raise AssertionError("met een leeg budget mag dit model niet draaien")

    governor = quant_cost_service.BudgetGovernor(session, now=NU)
    model = GuardedDecisionModel(
        NooitAangeroepen(), budget_check=governor.may_call, fallback=RulesOnly()
    )
    uitkomst = await model.decide(
        DecisionInput(hypothesis="H1_v1", features={"liquidity_usd": 50000.0})
    )
    stand = await quant_cost_service.budget_status(session, now=NU)
    print(f"  budgetstand:  {stand.mode.value} (EUR {stand.month_total_eur})")
    print(f"  model:        {uitkomst.model_name}")
    print(f"  degraded:     {uitkomst.degraded}")
    print(f"  reden:        {uitkomst.reason}")
    assert stand.mode is BudgetMode.LLM_OFF
    assert uitkomst.model_name == "rules_only" and uitkomst.degraded


async def main() -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", settings.database_url)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    database = Database.from_url(url)
    try:
        async with database.session() as session:
            await leegmaken(session)
            await risico(session)
            await kosten(session)
            await leegmaken(session)
            print("\nTabellen weer leeggemaakt.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
