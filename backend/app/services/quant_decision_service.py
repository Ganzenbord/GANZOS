"""De schaduwlog en het examen voor een nieuw beslismodel (sectie 7).

Een nieuw model mag niet meebeslissen omdat het nieuwer is. Het mag meebeslissen als het
over honderd beslissingen heeft laten zien dat het beter is dan `RulesOnly` — en "beter"
betekent hier een lagere Brier-score, niet een gevoel.

Zolang dat niet is aangetoond, is het antwoord "te vroeg". Dat is geen bescheidenheid maar
rekenkunde: met twintig beslissingen past bijna elke werkelijkheid in de uitkomst.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quantlab import QuantDecisionLog
from app.quantlab.brier import ReliabilityBin, brier_score, reliability
from app.quantlab.decision import SHADOW_DECISIONS_REQUIRED

# Het model waar een nieuw model tegen wordt afgemeten. Altijd beschikbaar, leert niets,
# en precies daarom de juiste maatstaf.
BASELINE = "rules_only"


@dataclass(frozen=True)
class ShadowVerdict:
    model_name: str
    hypothesis: str
    decisions: int
    with_outcome: int
    brier: Decimal | None
    baseline_brier: Decimal | None
    bins: tuple[ReliabilityBin, ...]
    conclusion_allowed: bool
    better_than_baseline: bool | None
    verdict: str


async def log_decision(
    session: AsyncSession,
    *,
    hypothesis: str,
    pool_address: str,
    model_name: str,
    score: float,
    used: bool,
    shadow: bool,
    degraded: bool,
) -> QuantDecisionLog:
    rij = QuantDecisionLog(
        hypothesis=hypothesis,
        pool_address=pool_address,
        model_name=model_name,
        score=Decimal(str(score)),
        used=used,
        shadow=shadow,
        degraded=degraded,
    )
    session.add(rij)
    await session.flush()
    return rij


async def record_outcome(
    session: AsyncSession, *, decision_id: int, profitable: bool
) -> None:
    """De uitkomst erbij, zodra de trade is gesloten.

    Apart van het loggen omdat het moment anders is: een beslissing wordt genomen voordat
    je weet hoe het afloopt. Een lege uitkomst betekent "weten we nog niet".
    """
    rij = await session.get(QuantDecisionLog, decision_id)
    if rij is not None:
        rij.outcome = profitable
    await session.flush()


async def _beslissingen(
    session: AsyncSession, *, model_name: str, hypothesis: str
) -> Sequence[QuantDecisionLog]:
    rijen = await session.execute(
        select(QuantDecisionLog).where(
            QuantDecisionLog.model_name == model_name,
            QuantDecisionLog.hypothesis == hypothesis,
        )
    )
    return list(rijen.scalars().all())


async def shadow_verdict(
    session: AsyncSession, *, model_name: str, hypothesis: str
) -> ShadowVerdict:
    """Mag dit model meebeslissen?

    Drie dingen moeten kloppen: er zijn genoeg beslissingen met een bekende uitkomst, de
    Brier-score is er, en hij is lager dan die van `RulesOnly` over dezelfde periode.
    """
    alles = await _beslissingen(session, model_name=model_name, hypothesis=hypothesis)
    met_uitkomst = [r for r in alles if r.outcome is not None]
    paren = [(float(r.score), bool(r.outcome)) for r in met_uitkomst]
    score = brier_score(paren)

    basis = await _beslissingen(session, model_name=BASELINE, hypothesis=hypothesis)
    basis_paren = [(float(r.score), bool(r.outcome)) for r in basis if r.outcome is not None]
    basis_score = brier_score(basis_paren)

    genoeg = len(met_uitkomst) >= SHADOW_DECISIONS_REQUIRED
    beter = (
        None
        if score is None or basis_score is None
        else bool(score < basis_score)
    )

    if not genoeg:
        oordeel = (
            f"Te vroeg: {len(met_uitkomst)} van de {SHADOW_DECISIONS_REQUIRED} beslissingen "
            "met een bekende uitkomst. Het model loopt in de schaduw en bepaalt niets."
        )
    elif beter is None:
        oordeel = (
            "Er is geen vergelijking mogelijk: van RulesOnly zijn over deze hypothese geen "
            "beslissingen met een uitkomst vastgelegd."
        )
    elif beter:
        oordeel = (
            f"Over {len(met_uitkomst)} beslissingen haalt {model_name} een Brier-score van "
            f"{score} tegen {basis_score} voor {BASELINE}. Lager is beter, dus dit model is "
            "beter gekalibreerd."
        )
    else:
        oordeel = (
            f"Over {len(met_uitkomst)} beslissingen haalt {model_name} een Brier-score van "
            f"{score} tegen {basis_score} voor {BASELINE}. Niet beter, dus uitzetten."
        )

    return ShadowVerdict(
        model_name=model_name,
        hypothesis=hypothesis,
        decisions=len(alles),
        with_outcome=len(met_uitkomst),
        brier=score,
        baseline_brier=basis_score,
        bins=tuple(reliability(paren)) if paren else (),
        conclusion_allowed=genoeg,
        better_than_baseline=beter,
        verdict=oordeel,
    )
