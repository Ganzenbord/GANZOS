"""Welke skill hoort bij deze opdracht?

Twee manieren om te vergelijken, achter hetzelfde koppelvlak:

- **Woorden** (`LexicalMatcher`) — telt hoeveel woorden een opdracht deelt met de naam, de
  omschrijving en het trigger_pattern van een skill. Werkt altijd, heeft niets nodig, en is
  verrassend bruikbaar voor korte commando's.
- **Betekenis** (`EmbeddingMatcher`) — sentence-transformers, lokaal. Begrijpt dat "zet de
  video online" en "upload naar YouTube" hetzelfde bedoelen. Brengt torch mee, dus het zit
  in een aparte installatiestap.

Er gaat **nooit** iets naar een externe dienst om te matchen.

Welke van de twee er draaide staat in elke uitslag, en de reden ook — een verkeerde match
moet je achteraf kunnen navertellen.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.models.platform import Skill
from app.utils.embeddings import cosine_similarity

logger = logging.getLogger("ganz.skills")

# Woorden die in bijna elke opdracht staan en dus niets onderscheiden.
STOPWOORDEN = frozenset(
    """
    de het een en of maar want dus als dan die dat deze dit er is zijn was waren wordt worden
    ik jij je hij zij we wij jullie ze mijn jouw zijn haar ons onze aan af bij door in met na
    naar om op over te tot uit van voor bij nog even eens graag alsjeblieft kun kan kunt wil
    wilt moet moeten ga gaan doe doen maak maken zet zetten
    """.split()
)


@dataclass(frozen=True, slots=True)
class SkillMatch:
    skill: Skill | None
    confidence: float
    threshold: float
    reason: str
    backend: str

    @property
    def matched(self) -> bool:
        return self.skill is not None


@runtime_checkable
class SkillMatcher(Protocol):
    @property
    def backend(self) -> str:
        """Welke manier van vergelijken dit is. Komt mee in de uitslag en het logboek."""

    async def match(
        self, opdracht: str, skills: Sequence[Skill], *, threshold: float
    ) -> SkillMatch:
        """Zoek de best passende skill, of leg uit waarom er geen is."""


def tokenize(tekst: str) -> set[str]:
    """Breek een zin op in betekenisdragende woorden."""
    woorden = re.findall(r"[a-z0-9]+", (tekst or "").lower())
    return {w for w in woorden if len(w) > 2 and w not in STOPWOORDEN}


def skill_woorden(skill: Skill) -> set[str]:
    """Alles waar een skill op herkend mag worden."""
    delen = [skill.name or "", skill.description or "", skill.trigger_pattern or ""]
    return tokenize(" ".join(delen))


def skill_tekst(skill: Skill) -> str:
    """Dezelfde velden, maar als lopende tekst — dat is wat een taalmodel nodig heeft."""
    delen = [skill.name or "", skill.description or "", (skill.trigger_pattern or "").replace("|", ", ")]
    return ". ".join(deel.strip() for deel in delen if deel.strip())


class LexicalMatcher:
    """Vergelijken op gedeelde woorden. Heeft niets nodig en doet het altijd."""

    backend = "woorden"

    async def match(
        self, opdracht: str, skills: Sequence[Skill], *, threshold: float
    ) -> SkillMatch:
        gevraagd = tokenize(opdracht)
        if not gevraagd:
            return SkillMatch(
                None, 0.0, threshold, "De opdracht bevat geen woorden om op te zoeken.", self.backend
            )
        if not skills:
            return SkillMatch(None, 0.0, threshold, "Er zijn nog geen skills.", self.backend)

        scores: list[tuple[float, Skill, set[str]]] = []
        for skill in skills:
            hunne = skill_woorden(skill)
            if not hunne:
                continue
            gedeeld = gevraagd & hunne
            # Delen door het kleinste van de twee: een korte skillnaam die helemaal in de
            # opdracht voorkomt telt dan even zwaar als andersom.
            noemer = min(len(gevraagd), len(hunne)) or 1
            scores.append((len(gedeeld) / noemer, skill, gedeeld))

        if not scores:
            return SkillMatch(
                None, 0.0, threshold, "Geen enkele skill heeft woorden om op te zoeken.", self.backend
            )

        scores.sort(key=lambda rij: rij[0], reverse=True)
        score, skill, gedeeld = scores[0]
        woorden = ", ".join(sorted(gedeeld)) or "niets"

        if score < threshold:
            return SkillMatch(
                None,
                round(score, 4),
                threshold,
                f"Beste was '{skill.name}' met {score:.2f} (gedeelde woorden: {woorden}), "
                f"onder de drempel van {threshold:.2f}.",
                self.backend,
            )
        return SkillMatch(
            skill,
            round(score, 4),
            threshold,
            f"'{skill.name}' met {score:.2f} (gedeelde woorden: {woorden}).",
            self.backend,
        )


class EmbeddingMatcher:
    """Vergelijken op betekenis, met een taalmodel dat lokaal draait."""

    backend = "betekenis"

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any | None = None

    async def match(
        self, opdracht: str, skills: Sequence[Skill], *, threshold: float
    ) -> SkillMatch:
        import anyio

        if not skills:
            return SkillMatch(None, 0.0, threshold, "Er zijn nog geen skills.", self.backend)

        model = await anyio.to_thread.run_sync(self._load)
        teksten = [skill_tekst(skill) for skill in skills]
        afdrukken = await anyio.to_thread.run_sync(self._encode, model, [opdracht, *teksten])

        gevraagd, rest = afdrukken[0], afdrukken[1:]
        scores = sorted(
            ((cosine_similarity(gevraagd, afdruk), skill) for afdruk, skill in zip(rest, skills, strict=True)),
            key=lambda rij: rij[0],
            reverse=True,
        )
        score, skill = scores[0]
        if score < threshold:
            return SkillMatch(
                None,
                round(score, 4),
                threshold,
                f"Beste was '{skill.name}' met {score:.2f}, onder de drempel van {threshold:.2f}.",
                self.backend,
            )
        return SkillMatch(skill, round(score, 4), threshold, f"'{skill.name}' met {score:.2f}.", self.backend)

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - hangt van de installatie af
            raise SkillMatcherUnavailableError(
                "Matchen op betekenis is niet geïnstalleerd. Installeer het eenmalig met: "
                "pip install -r requirements-skills.txt (dat haalt sentence-transformers en "
                "torch op). Zonder die stap matcht Ganz op woorden."
            ) from exc
        self._model = SentenceTransformer(self._model_name, cache_folder=self._cache_dir)
        return self._model

    def _encode(self, model: Any, teksten: list[str]) -> list[list[float]]:
        return [list(map(float, rij)) for rij in model.encode(teksten, normalize_embeddings=True)]


class SkillMatcherUnavailableError(RuntimeError):
    """Het taalmodel kan niet geladen worden. De tekst is bedoeld voor de gebruiker."""


class FallbackMatcher:
    """Probeert betekenis, valt terug op woorden als het model er niet is.

    Met opzet géén stille terugval: welke van de twee het werd staat in elke uitslag en gaat
    één keer als waarschuwing naar het logboek. Anders zou je je afvragen waarom het matchen
    ineens slechter is zonder dat iets dat zegt.
    """

    def __init__(self, voorkeur: SkillMatcher, terugval: SkillMatcher) -> None:
        self._voorkeur = voorkeur
        self._terugval = terugval
        self._gewaarschuwd = False

    @property
    def backend(self) -> str:
        return self._voorkeur.backend

    async def match(
        self, opdracht: str, skills: Sequence[Skill], *, threshold: float
    ) -> SkillMatch:
        try:
            return await self._voorkeur.match(opdracht, skills, threshold=threshold)
        except SkillMatcherUnavailableError as exc:
            if not self._gewaarschuwd:
                logger.warning("%s Er wordt op woorden gematcht.", exc)
                self._gewaarschuwd = True
            return await self._terugval.match(opdracht, skills, threshold=threshold)
