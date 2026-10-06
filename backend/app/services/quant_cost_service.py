"""Het kostenboek met een database eronder.

Boeken, optellen en de vraag "mag deze aanroep nog". Het rekenen zelf staat in
`app/quantlab/pricing.py` en het beleid in `app/quantlab/budget.py`; dit bestand doet
alleen het praten met de database.

Eén regel die het geheel draagt: een aanroep van een model waarvan de prijs niet bekend
is, wordt niet geboekt en gaat dus ook niet door. Nul euro boeken voor iets dat wel geld
kost, zou betekenen dat het plafond nooit wordt gehaald en het budget niets doet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quantlab import QuantLlmCall
from app.quantlab.agents import QuantAgent
from app.quantlab.budget_limits import MONTHLY_HARD_CAP_EUR
from app.quantlab.budget import (
    BudgetStatus,
    BudgetVerdict,
    SpendSnapshot,
    evaluate_call,
    status_from,
)
from app.quantlab.pricing import TokenUsage, cost_eur, cost_usd

# Standaardkoers dollar naar euro. Dit is géén gemeten koers — zie de openstaande vraag in
# het fase 1-rapport. Elke boeking bewaart de koers waarmee is gerekend, dus het boek
# blijft narekenbaar als de werkelijke koers afwijkt.
DEFAULT_USD_EUR_RATE = Decimal("0.92")


def month_start(now: datetime) -> datetime:
    moment = now.astimezone(timezone.utc)
    return datetime(moment.year, moment.month, 1, tzinfo=timezone.utc)


def day_start(now: datetime) -> datetime:
    moment = now.astimezone(timezone.utc)
    return datetime.combine(moment.date(), time.min, tzinfo=timezone.utc)


async def book_call(
    session: AsyncSession,
    *,
    agent: QuantAgent,
    model: str,
    usage: TokenUsage,
    purpose: str,
    rate: Decimal = DEFAULT_USD_EUR_RATE,
    now: datetime | None = None,
) -> QuantLlmCall:
    """Boek één aanroep. Gooit `UnknownModelPrice` als de prijs niet bekend is.

    De aanroeper commit zelf; valt de rest van de handeling om, dan hoort deze rij er ook
    niet te staan.
    """
    rij = QuantLlmCall(
        agent=agent.value,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cost_usd=cost_usd(model, usage),
        cost_eur=cost_eur(model, usage, rate=rate),
        fx_rate=rate,
        purpose=purpose[:120],
    )
    if now is not None:
        rij.created_at = now.astimezone(timezone.utc)
    session.add(rij)
    await session.flush()
    return rij


async def _som_per_agent(
    session: AsyncSession, vanaf: datetime, tot: datetime | None = None
) -> dict[QuantAgent, Decimal]:
    query = (
        select(QuantLlmCall.agent, func.coalesce(func.sum(QuantLlmCall.cost_eur), 0))
        .where(QuantLlmCall.created_at >= vanaf)
        .group_by(QuantLlmCall.agent)
    )
    if tot is not None:
        query = query.where(QuantLlmCall.created_at < tot)
    uit: dict[QuantAgent, Decimal] = {}
    for naam, bedrag in (await session.execute(query)).all():
        try:
            uit[QuantAgent(naam)] = Decimal(str(bedrag or 0))
        except ValueError:
            # Een agent die niet meer bestaat. De rij blijft staan (het boek is
            # onveranderlijk), maar hij telt niet mee in een grens die niemand meer heeft.
            continue
    return uit


async def spend_snapshot(
    session: AsyncSession, *, now: datetime | None = None
) -> SpendSnapshot:
    """Wat er deze maand en vandaag is uitgegeven, per agent en in totaal."""
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    begin_maand = month_start(nu)
    per_maand = await _som_per_agent(session, begin_maand)
    per_dag = await _som_per_agent(session, day_start(nu))
    totaal = await session.scalar(
        select(func.coalesce(func.sum(QuantLlmCall.cost_eur), 0)).where(
            QuantLlmCall.created_at >= begin_maand
        )
    )
    return SpendSnapshot(
        day=nu.date(),
        month_total_eur=Decimal(str(totaal or 0)),
        month_per_agent_eur=per_maand,
        day_per_agent_eur=per_dag,
    )


async def budget_status(
    session: AsyncSession, *, now: datetime | None = None
) -> BudgetStatus:
    return status_from(await spend_snapshot(session, now=now))


class BudgetGovernor:
    """De budget governor zoals een beslismodel hem gebruikt.

    `may_call` past precies op `GuardedDecisionModel(budget_check=...)`. De stand wordt per
    aanroep opnieuw opgeteld: een governor die zijn eigen totaal bijhoudt, loopt uiteen met
    het boek zodra er twee processen draaien, en in fase 2 draaien er twee processen.
    """

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now

    async def may_call(self, agent: QuantAgent, estimated_eur: Decimal) -> BudgetVerdict:
        stand = await spend_snapshot(self._session, now=self._now)
        return evaluate_call(stand, agent, estimated_eur)


async def recent_calls(session: AsyncSession, *, limit: int = 20) -> list[QuantLlmCall]:
    rijen = await session.execute(
        select(QuantLlmCall).order_by(QuantLlmCall.id.desc()).limit(limit)
    )
    return list(rijen.scalars().all())


async def spend_on_day(session: AsyncSession, *, day: date) -> Decimal:
    """Wat één UTC-dag heeft gekost. Voor het dagrapport."""
    begin = datetime.combine(day, time.min, tzinfo=timezone.utc)
    totaal = await session.scalar(
        select(func.coalesce(func.sum(QuantLlmCall.cost_eur), 0)).where(
            QuantLlmCall.created_at >= begin,
            QuantLlmCall.created_at < begin + timedelta(days=1),
        )
    )
    return Decimal(str(totaal or 0))


@dataclass(frozen=True)
class CostProjection:
    days_measured: float
    calls: int
    spent_eur: Decimal
    eur_per_day: Decimal
    projected_month_eur: Decimal
    monthly_cap_eur: Decimal
    within_budget: bool
    per_agent_month_eur: dict[str, Decimal]
    explanation: str


async def cost_projection(
    session: AsyncSession, *, now: datetime | None = None, days_in_month: int = 30
) -> CostProjection:
    """De verwachte maandkosten uit de werkelijke aanroepen (sectie 12, na fase 4).

    Een meting en geen schatting: wat er is uitgegeven, gedeeld door de tijd die werkelijk
    is gemeten. Komt de projectie boven de 200 euro, dan is het antwoord uit de opdracht
    ondubbelzinnig — het ontwerp aanpassen, niet het budget.

    Er zit geen marge in. Een projectie met een veiligheidsmarge is een getal waar je niet
    meer op kunt rekenen, want je weet niet meer welk deel meting is.
    """
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    eerste = await session.scalar(select(func.min(QuantLlmCall.created_at)))
    laatste = await session.scalar(select(func.max(QuantLlmCall.created_at)))
    aantal = int(
        await session.scalar(select(func.count()).select_from(QuantLlmCall)) or 0
    )
    uitgegeven = Decimal(
        str(
            await session.scalar(
                select(func.coalesce(func.sum(QuantLlmCall.cost_eur), 0))
            )
            or 0
        )
    )

    if not aantal or eerste is None or laatste is None:
        return CostProjection(
            days_measured=0.0,
            calls=0,
            spent_eur=Decimal("0"),
            eur_per_day=Decimal("0"),
            projected_month_eur=Decimal("0"),
            monthly_cap_eur=MONTHLY_HARD_CAP_EUR,
            within_budget=True,
            per_agent_month_eur={},
            explanation=(
                "Er zijn geen aanroepen geboekt, dus er is geen projectie te maken. Dat is "
                "geen goed nieuws en geen slecht nieuws: er is nog niets gemeten."
            ),
        )

    # Het aantal UTC-dagen waarop er werkelijk is aangeroepen, en niet de tijdspanne
    # tussen de eerste en de laatste aanroep. Dat scheelt: drie dagen aanroepen geeft een
    # spanne van twee dagen, en dan komt de dagprijs 50% te hoog uit. Een projectie die
    # structureel te hoog is, is net zo onbruikbaar als een die te laag is — je weet niet
    # meer welk deel meting is.
    dagen_met_aanroepen = int(
        await session.scalar(
            select(func.count(func.distinct(func.date(QuantLlmCall.created_at))))
        )
        or 0
    )
    dagen = float(max(dagen_met_aanroepen, 1))
    per_dag = (uitgegeven / Decimal(str(dagen))).quantize(Decimal("0.000001"))
    projectie = (per_dag * Decimal(days_in_month)).quantize(Decimal("0.01"))

    per_agent: dict[str, Decimal] = {}
    rijen = await session.execute(
        select(QuantLlmCall.agent, func.coalesce(func.sum(QuantLlmCall.cost_eur), 0))
        .group_by(QuantLlmCall.agent)
    )
    for naam, bedrag in rijen.all():
        per_agent[str(naam)] = (
            Decimal(str(bedrag or 0)) / Decimal(str(dagen)) * Decimal(days_in_month)
        ).quantize(Decimal("0.01"))

    binnen = projectie <= MONTHLY_HARD_CAP_EUR
    uitleg = (
        f"Op {int(dagen)} dagen zijn er {aantal} aanroepen geboekt voor "
        f"EUR {uitgegeven.quantize(Decimal('0.01'))}, dus EUR {per_dag.quantize(Decimal('0.01'))} "
        f"per dag. Dat projecteert naar EUR {projectie} per maand van {days_in_month} dagen."
    )
    if binnen:
        uitleg += f" Dat blijft onder het plafond van EUR {MONTHLY_HARD_CAP_EUR}."
    else:
        uitleg += (
            f" Dat is boven het plafond van EUR {MONTHLY_HARD_CAP_EUR}. Volgens sectie 12 "
            "is het antwoord dan het ontwerp aanpassen en niet het budget: minder context "
            "voor de Reviewer, of de Analyst minder vaak aanroepen."
        )
    return CostProjection(
        days_measured=dagen,
        calls=aantal,
        spent_eur=uitgegeven,
        eur_per_day=per_dag,
        projected_month_eur=projectie,
        monthly_cap_eur=MONTHLY_HARD_CAP_EUR,
        within_budget=binnen,
        per_agent_month_eur=per_agent,
        explanation=uitleg,
    )
