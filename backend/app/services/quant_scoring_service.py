"""De scoringsronde: hier mag een model aan te pas komen, en nergens anders.

Dit bestand staat met opzet buiten het pad waarin een trade tot stand komt. De scheiding is
de hele architectuur van sectie 6:

- **hier** worden kandidaten gescoord, en dat mag met `RulesOnly`, met JEV of met een
  Claude-model. Het mag wachten, het mag falen, het mag een antwoord geven dat niet in het
  schema past — dat wordt opgevangen.
- **daar** (`app/quantlab/engine.py`) wordt besloten, en dat gebeurt uitsluitend op scores
  die hier al zijn weggeschreven, plus deterministische regels.

Een nieuw model loopt eerst mee in de schaduw: zijn score wordt vastgelegd en niet gebruikt.
Pas als de Brier-score over honderd beslissingen beter is dan die van `RulesOnly`, mag het
meebeslissen. Zie `quant_decision_service.shadow_verdict`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.quantlab.decision import DecisionInput, DecisionModel
from app.quantlab.strategy import Candidate
from app.services import quant_decision_service

logger = logging.getLogger("ganz.quantlab.scoring")


@dataclass(frozen=True)
class ScoringResult:
    scored: int
    degraded: int
    shadow_logged: int
    scores: dict[str, float]


async def score_candidates(
    session: AsyncSession,
    *,
    hypothesis: str,
    candidates: Sequence[Candidate],
    model: DecisionModel,
    shadow_model: DecisionModel | None = None,
) -> ScoringResult:
    """Scoor elke kandidaat één keer en leg het vast.

    `shadow_model` loopt mee zonder iets te bepalen. Zijn score komt in dezelfde log met
    `used=False` en `shadow=True`, zodat je later kunt narekenen of hij beter was geweest.
    Klapt hij eruit, dan verandert dat niets aan de score die wél wordt gebruikt — dat is
    het hele punt van schaduwdraaien.
    """
    scores: dict[str, float] = {}
    degraded = schaduw = 0

    # Eén score per pool: een pool die twintig keer tickt, hoeft niet twintig keer gescoord.
    # Dat is niet alleen zuinig maar ook juist — de score hoort bij het token en niet bij
    # het moment.
    gezien: set[str] = set()
    for kandidaat in candidates:
        if kandidaat.pool_address in gezien:
            continue
        gezien.add(kandidaat.pool_address)

        opdracht = DecisionInput(
            hypothesis=hypothesis,
            features={
                "liquidity_usd": float(kandidaat.liquidity_usd or 0),
                "volume_usd": float(kandidaat.volume_usd or 0),
                "price_usd": float(kandidaat.price_usd or 0),
            },
        )
        uitkomst = await model.decide(opdracht)
        scores[kandidaat.pool_address] = uitkomst.score
        degraded += 1 if uitkomst.degraded else 0
        await quant_decision_service.log_decision(
            session,
            hypothesis=hypothesis,
            pool_address=kandidaat.pool_address,
            model_name=uitkomst.model_name,
            score=uitkomst.score,
            used=True,
            shadow=False,
            degraded=uitkomst.degraded,
        )

        if shadow_model is not None:
            try:
                schaduw_uit = await shadow_model.decide(opdracht)
            except Exception as fout:  # noqa: BLE001 - een schaduw mag alles behalve storen
                logger.info("Schaduwmodel gaf niets bruikbaars: %s", fout)
                continue
            await quant_decision_service.log_decision(
                session,
                hypothesis=hypothesis,
                pool_address=kandidaat.pool_address,
                model_name=schaduw_uit.model_name,
                score=schaduw_uit.score,
                used=False,
                shadow=True,
                degraded=schaduw_uit.degraded,
            )
            schaduw += 1

    await session.flush()
    return ScoringResult(
        scored=len(scores), degraded=degraded, shadow_logged=schaduw, scores=scores
    )
