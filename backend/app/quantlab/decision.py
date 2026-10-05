"""Beslismodellen (sectie 7).

Eén contract, drie implementaties, en een vangnet dat altijd werkt:

- `RulesOnly`      — pure code, geen netwerk, geen sleutel, geen budget. De standaard.
- `JevClassifier`  — JEV.ai, dat we willen gaan gebruiken. Geeft alleen een score.
- `LlmClassifier`  — een Claude-model, ook alleen voor een score.

Twee regels uit de opdracht zitten in de code en niet in een afspraak:

1. **Schaduwmodus.** Een nieuw model draait de eerste 100 beslissingen mee zonder iets te
   bepalen (`ShadowDecisionModel`). Daarna kun je het vergelijken met `RulesOnly` — pas
   dán mag het meebeslissen.
2. **Niets repareren.** Een antwoord dat niet in het schema past, wordt weggegooid,
   gelogd en geteld. Van een score van 1,7 een 1,0 maken is het ergste wat je kunt doen:
   dan ziet niemand ooit dat het model iets anders zei dan afgesproken.

De modellen hier krijgen hun client mee en openen zelf geen verbinding. Zo heeft deze laag
geen netwerk nodig om getest te worden, en kan een Analyst of Classifier niet zelf iets
anders gaan ophalen dan waarvoor hij is bedoeld.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.quantlab.agents import QuantAgent
from app.quantlab.budget import BudgetVerdict
from app.quantlab.scores import is_valid_score

logger = logging.getLogger("ganz.quantlab.decision")

# Hoeveel beslissingen een nieuw model meeloopt zonder iets te bepalen, voordat het mag
# meebeslissen. Sectie 7 van de opdracht; daarna volgt de betrouwbaarheidsanalyse en de
# Brier-score tegen RulesOnly.
SHADOW_DECISIONS_REQUIRED = 100

# Hoe lang het lab op een model wacht. Langer wachten is geen optie: er staat een kandidaat
# van tien minuten oud aan de andere kant.
DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class DecisionInput:
    """Wat een model te zien krijgt: alleen getallen.

    Met opzet geen vrije tekst van buiten. Namen, beschrijvingen en socials van een token
    zijn invoer van een vreemde (sectie 10); die horen in een afgebakend datablok en niet
    in de kenmerken waarop een score wordt gegeven.
    """

    hypothesis: str
    features: Mapping[str, float]


@dataclass(frozen=True)
class DecisionOutput:
    score: float
    model_name: str
    degraded: bool
    reason: str


@runtime_checkable
class DecisionModel(Protocol):
    """Het contract. `estimated_eur` is wat één aanroep ongeveer kost, voor de governor."""

    name: str
    agent: QuantAgent
    estimated_eur: Decimal

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput: ...


# Een regelset krijgt de kenmerken en geeft een score met een uitleg terug.
RuleSet = Callable[[Mapping[str, float]], tuple[float, str]]


def no_rules_yet(features: Mapping[str, float]) -> tuple[float, str]:
    """De regelset die er in fase 1 is: nog geen enkele regel.

    Dit geeft bewust 0,0 en geen "wel aardig". Fase 1 legt het contract en het vangnet
    vast; de echte filters horen bij hypothese H1 en komen in een latere fase. Een
    verzonnen score zou precies het soort cijfer zijn waar deze opdracht tegen waarschuwt.
    """
    return 0.0, "Nog geen regels geregistreerd; de filters van H1 komen in een latere fase."


class RulesOnly:
    """Het vangnet. Werkt altijd: geen netwerk, geen sleutel, geen budget.

    Dit is de standaard en blijft de standaard. Een model mag het overnemen als het in de
    schaduw heeft bewezen dat het beter is, niet omdat het nieuwer is.
    """

    name = "rules_only"
    agent = QuantAgent.SCREENER
    estimated_eur = Decimal("0")

    def __init__(self, rules: RuleSet | None = None) -> None:
        self._rules = rules or no_rules_yet

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        score, uitleg = self._rules(opdracht.features)
        if not is_valid_score(score):
            # Een eigen regelset die onzin teruggeeft, is een programmeerfout en geen
            # degradatie: hier valt niets op terug te vallen.
            raise ValueError(f"De regelset gaf geen geldige score: {score!r}")
        return DecisionOutput(
            score=float(score), model_name=self.name, degraded=False, reason=uitleg
        )


@runtime_checkable
class ScoreClient(Protocol):
    """Alles wat een score kan geven op een rij kenmerken. Niets meer dan dat."""

    async def score(self, hypothesis: str, features: Mapping[str, float]) -> float: ...


class JevClassifier:
    """JEV.ai als classifier.

    De client wordt meegegeven en staat niet in dit bestand: wat JEV precies aanbiedt en
    wat het kost, is vanuit deze omgeving niet te verifiëren. Zolang het model niet met
    prijs en bron in `pricing.py` staat, kan een aanroep niet geboekt worden en draait hij
    dus ook niet — zie de openstaande vraag in het fase 1-rapport.

    Volgens sectie 7 begint JEV in de schaduw: 100 beslissingen meelopen, dan de
    betrouwbaarheid en de Brier-score tegen `RulesOnly`, en pas daarna meebeslissen.
    """

    agent = QuantAgent.CLASSIFIER

    def __init__(
        self, client: ScoreClient, *, model: str, estimated_eur: Decimal, name: str = "jev"
    ) -> None:
        self.name = name
        self.model = model
        self.estimated_eur = estimated_eur
        self._client = client

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        score = await self._client.score(opdracht.hypothesis, opdracht.features)
        return DecisionOutput(
            score=score, model_name=self.name, degraded=False, reason=f"Score van {self.model}."
        )


class LlmClassifier:
    """Een Claude-model als classifier. Geeft alleen een score, geen vrije tekst.

    Ook hier komt de client van buiten: deze laag praat niet zelf met het netwerk, zodat
    een Classifier geen enkele kant op kan die niet in zijn opdracht staat.
    """

    agent = QuantAgent.CLASSIFIER

    def __init__(
        self, client: ScoreClient, *, model: str, estimated_eur: Decimal
    ) -> None:
        self.name = model
        self.model = model
        self.estimated_eur = estimated_eur
        self._client = client

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        score = await self._client.score(opdracht.hypothesis, opdracht.features)
        return DecisionOutput(
            score=score, model_name=self.name, degraded=False, reason=f"Score van {self.model}."
        )


BudgetCheck = Callable[[QuantAgent, Decimal], Awaitable[BudgetVerdict]]


class GuardedDecisionModel:
    """Een model met het budget, de klok en het schema eromheen.

    Vier dingen kunnen misgaan, en alle vier leiden tot hetzelfde: terugvallen op
    `RulesOnly` en het resultaat markeren als `degraded`.

    1. het budget is op of de agent is door zijn grens heen;
    2. het model antwoordt niet op tijd;
    3. het model antwoordt met iets dat niet in het schema past;
    4. het model klapt eruit.

    De tellers zijn er niet voor de sier. "Het lab draait" en "het lab draait op het
    vangnet" zien er in de uitkomsten hetzelfde uit, en dat is precies het soort verschil
    dat je wilt kunnen zien in een rapport.
    """

    def __init__(
        self,
        primary: DecisionModel,
        *,
        budget_check: BudgetCheck,
        fallback: DecisionModel | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RulesOnly()
        self.name = primary.name
        self.agent = primary.agent
        self.estimated_eur = primary.estimated_eur
        self._budget_check = budget_check
        self._timeout = timeout_seconds
        self.budget_blocked = 0
        self.timeouts = 0
        self.discarded = 0
        self.failures = 0

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        verdict = await self._budget_check(self.primary.agent, self.primary.estimated_eur)
        if not verdict.allowed:
            self.budget_blocked += 1
            return await self._terugval(opdracht, f"Budget: {verdict.reason}")

        try:
            uitkomst = await asyncio.wait_for(
                self.primary.decide(opdracht), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            self.timeouts += 1
            logger.warning(
                "Model %s antwoordde niet binnen %.1fs; terugval op %s",
                self.primary.name,
                self._timeout,
                self.fallback.name,
            )
            return await self._terugval(
                opdracht, f"{self.primary.name} antwoordde niet binnen {self._timeout:g} seconden."
            )
        except Exception as fout:  # noqa: BLE001 - elke fout is een degradatie, geen crash
            self.failures += 1
            logger.warning("Model %s klapte eruit: %s", self.primary.name, fout)
            return await self._terugval(
                opdracht, f"{self.primary.name} gaf een fout; het lab gaat door op de regels."
            )

        if not isinstance(uitkomst, DecisionOutput) or not is_valid_score(uitkomst.score):
            # Weggooien, loggen, tellen. Niet repareren: een score van 1,7 naar 1,0
            # bijstellen verbergt precies wat je wilde weten.
            self.discarded += 1
            logger.warning(
                "Antwoord van %s valt buiten het schema en is weggegooid", self.primary.name
            )
            return await self._terugval(
                opdracht,
                f"{self.primary.name} gaf een antwoord buiten het schema; dat is weggegooid.",
            )
        return uitkomst

    async def _terugval(self, opdracht: DecisionInput, waarom: str) -> DecisionOutput:
        uitkomst = await self.fallback.decide(opdracht)
        return DecisionOutput(
            score=uitkomst.score,
            model_name=uitkomst.model_name,
            degraded=True,
            reason=f"{waarom} Teruggevallen op {uitkomst.model_name}.",
        )


ShadowLogger = Callable[[str, float | None], Awaitable[None]]


class ShadowDecisionModel:
    """Laat een model meelopen zonder het iets te laten bepalen (sectie 7).

    Wat het schaduwmodel zegt, wordt gelogd en nergens anders gebruikt. Klapt het eruit of
    duurt het te lang, dan verandert dat niets aan het besluit — dat is het hele punt van
    schaduwdraaien: je kunt het aanzetten zonder iets te riskeren.
    """

    def __init__(
        self,
        *,
        used: DecisionModel,
        shadow: DecisionModel,
        on_result: ShadowLogger,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.used = used
        self.shadow = shadow
        self.name = used.name
        self.agent = used.agent
        self.estimated_eur = used.estimated_eur
        self._on_result = on_result
        self._timeout = timeout_seconds

    async def decide(self, opdracht: DecisionInput) -> DecisionOutput:
        besluit = await self.used.decide(opdracht)
        score: float | None = None
        try:
            schaduw = await asyncio.wait_for(
                self.shadow.decide(opdracht), timeout=self._timeout
            )
            if is_valid_score(schaduw.score):
                score = float(schaduw.score)
        except Exception as fout:  # noqa: BLE001 - een schaduw mag alles behalve storen
            logger.info("Schaduwmodel %s gaf niets bruikbaars: %s", self.shadow.name, fout)
        await self._on_result(self.shadow.name, score)
        return besluit
