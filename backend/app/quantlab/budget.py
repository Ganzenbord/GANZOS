"""De budget governor, als pure functies (sectie 12).

Twee vragen, en beide zonder database: mag deze agent nu een model aanroepen, en in welke
stand staat het budget? De stand van de uitgaven komt er als `SpendSnapshot` in; waar die
vandaan komt is de zorg van `app/services/quant_cost_service.py`.

De uitkomst is nooit "een beetje". Of de aanroep mag, of hij mag niet met een reden die
op het scherm kan. Loopt het budget leeg, dan gaat het lab niet uit: het draait door op
`RulesOnly` en elk resultaat is vanaf dat moment gemarkeerd als `degraded`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.quantlab.agents import QuantAgent
from app.quantlab.budget_limits import (
    AGENT_MONTHLY_BUDGET_EUR,
    MONTHLY_HARD_CAP_EUR,
    MONTHLY_WARNING_EUR,
    daily_cap_eur,
    monthly_budget_eur,
)

__all__ = [
    "AgentSpend",
    "BudgetMode",
    "BudgetStatus",
    "BudgetVerdict",
    "BudgetVeto",
    "SpendSnapshot",
    "VETO_UITLEG",
    "budget_mode",
    "daily_cap_eur",
    "evaluate_call",
    "status_from",
]


class BudgetMode(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    LLM_OFF = "llm_off"


MODE_UITLEG: dict[BudgetMode, str] = {
    BudgetMode.NORMAL: "Het budget is op orde.",
    BudgetMode.WARNING: (
        "Meer dan 150 euro van de 200 is op. Het lab draait gewoon door, maar het is "
        "tijd om te kijken waar het geld heen gaat."
    ),
    BudgetMode.LLM_OFF: (
        "Het maandbudget is op. De taalmodellen staan uit; het lab draait door op de "
        "regels (RulesOnly) en alles wat er vanaf nu uitkomt is gemarkeerd als degraded."
    ),
}


class BudgetVeto(StrEnum):
    MONTH_CAP_REACHED = "month_cap_reached"
    AGENT_MONTH_CAP_REACHED = "agent_month_cap_reached"
    AGENT_DAY_CAP_REACHED = "agent_day_cap_reached"
    AGENT_WITHOUT_BUDGET = "agent_without_budget"


VETO_UITLEG: dict[BudgetVeto, str] = {
    BudgetVeto.MONTH_CAP_REACHED: (
        "Deze aanroep zou het maandplafond van 200 euro doorbreken. De taalmodellen gaan "
        "uit; het lab gaat door op de regels."
    ),
    BudgetVeto.AGENT_MONTH_CAP_REACHED: (
        "Deze agent is door zijn eigen maandbudget heen. De reserve van 70 euro is niet "
        "automatisch beschikbaar: die uitgeven is een beslissing van Stef."
    ),
    BudgetVeto.AGENT_DAY_CAP_REACHED: (
        "Deze agent heeft vandaag zijn daggrens gehaald. Dat houdt een doorgedraaide dag "
        "tegen zonder de hele maand te verspelen; morgen mag het weer."
    ),
    BudgetVeto.AGENT_WITHOUT_BUDGET: (
        "Deze agent bestaat uit code en heeft geen budget. Een aanroep van een taalmodel "
        "namens hem is een fout in de code, niet een tekort aan geld."
    ),
}


@dataclass(frozen=True)
class SpendSnapshot:
    """Wat er tot nu toe is uitgegeven. Alle bedragen in euro's.

    De twee mappings mogen onvolledig zijn: een agent die nog niets heeft gekost, staat er
    niet in en telt als nul.
    """

    day: date
    month_total_eur: Decimal
    month_per_agent_eur: Mapping[QuantAgent, Decimal] = field(default_factory=dict)
    day_per_agent_eur: Mapping[QuantAgent, Decimal] = field(default_factory=dict)

    def month_of(self, agent: QuantAgent) -> Decimal:
        return self.month_per_agent_eur.get(agent, Decimal("0"))

    def day_of(self, agent: QuantAgent) -> Decimal:
        return self.day_per_agent_eur.get(agent, Decimal("0"))


@dataclass(frozen=True)
class BudgetVerdict:
    allowed: bool
    mode: BudgetMode
    veto: BudgetVeto | None
    reason: str
    estimated_eur: Decimal
    month_total_eur: Decimal
    month_remaining_eur: Decimal


@dataclass(frozen=True)
class AgentSpend:
    agent: QuantAgent
    monthly_budget_eur: Decimal
    month_spent_eur: Decimal
    daily_cap_eur: Decimal
    day_spent_eur: Decimal

    @property
    def month_remaining_eur(self) -> Decimal:
        return max(Decimal("0"), self.monthly_budget_eur - self.month_spent_eur)


@dataclass(frozen=True)
class BudgetStatus:
    mode: BudgetMode
    explanation: str
    month: str
    month_total_eur: Decimal
    monthly_cap_eur: Decimal
    monthly_warning_eur: Decimal
    month_remaining_eur: Decimal
    reserve_eur: Decimal
    agents: tuple[AgentSpend, ...]


def budget_mode(month_total_eur: Decimal) -> BudgetMode:
    if month_total_eur >= MONTHLY_HARD_CAP_EUR:
        return BudgetMode.LLM_OFF
    if month_total_eur >= MONTHLY_WARNING_EUR:
        return BudgetMode.WARNING
    return BudgetMode.NORMAL


def evaluate_call(
    spend: SpendSnapshot, agent: QuantAgent, estimated_eur: Decimal
) -> BudgetVerdict:
    """Mag deze agent nu een model aanroepen, als het ongeveer `estimated_eur` kost?

    De schatting hoort eerder te hoog dan te laag te zijn: we rekenen af op wat de aanroep
    werkelijk kostte, maar we beslissen vooraf en moeten dus de kant van de voorzichtigheid
    kiezen. Niet "tot het plafond en dan stoppen" maar "nooit erover": de aanroep die het
    plafond zou doorbreken, gaat niet.
    """
    stand = budget_mode(spend.month_total_eur)
    resterend = max(Decimal("0"), MONTHLY_HARD_CAP_EUR - spend.month_total_eur)

    def antwoord(veto: BudgetVeto | None, *, mode: BudgetMode | None = None) -> BudgetVerdict:
        return BudgetVerdict(
            allowed=veto is None,
            mode=mode or stand,
            veto=veto,
            reason=VETO_UITLEG[veto] if veto else MODE_UITLEG[mode or stand],
            estimated_eur=estimated_eur,
            month_total_eur=spend.month_total_eur,
            month_remaining_eur=resterend,
        )

    if agent not in AGENT_MONTHLY_BUDGET_EUR:
        return antwoord(BudgetVeto.AGENT_WITHOUT_BUDGET)
    if spend.month_total_eur + estimated_eur > MONTHLY_HARD_CAP_EUR:
        return antwoord(BudgetVeto.MONTH_CAP_REACHED, mode=BudgetMode.LLM_OFF)
    if spend.month_of(agent) + estimated_eur > monthly_budget_eur(agent):
        return antwoord(BudgetVeto.AGENT_MONTH_CAP_REACHED)
    if spend.day_of(agent) + estimated_eur > daily_cap_eur(agent, spend.day):
        return antwoord(BudgetVeto.AGENT_DAY_CAP_REACHED)
    return antwoord(None)


def status_from(spend: SpendSnapshot) -> BudgetStatus:
    """De stand voor het scherm: één stoplicht en een regel per agent met een budget."""
    from app.quantlab.budget_limits import RESERVE_EUR

    stand = budget_mode(spend.month_total_eur)
    return BudgetStatus(
        mode=stand,
        explanation=MODE_UITLEG[stand],
        month=spend.day.strftime("%Y-%m"),
        month_total_eur=spend.month_total_eur,
        monthly_cap_eur=MONTHLY_HARD_CAP_EUR,
        monthly_warning_eur=MONTHLY_WARNING_EUR,
        month_remaining_eur=max(Decimal("0"), MONTHLY_HARD_CAP_EUR - spend.month_total_eur),
        reserve_eur=RESERVE_EUR,
        agents=tuple(
            AgentSpend(
                agent=agent,
                monthly_budget_eur=budget,
                month_spent_eur=spend.month_of(agent),
                daily_cap_eur=daily_cap_eur(agent, spend.day),
                day_spent_eur=spend.day_of(agent),
            )
            for agent, budget in AGENT_MONTHLY_BUDGET_EUR.items()
        ),
    )
