"""Stemafdrukken vergelijken. Puur rekenwerk, zonder database of netwerk."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


class EmbeddingError(ValueError):
    """De afdruk is onbruikbaar, bijvoorbeeld helemaal nul."""


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """Breng een afdruk terug tot lengte 1.

    Daarna is vergelijken niets anders dan de getallen paarsgewijs vermenigvuldigen en
    optellen, en ligt de uitkomst altijd tussen -1 en 1.
    """
    if not vector:
        raise EmbeddingError("Een lege afdruk kan niet vergeleken worden.")
    lengte = math.sqrt(sum(float(w) * float(w) for w in vector))
    if lengte == 0.0 or not math.isfinite(lengte):
        raise EmbeddingError("Deze afdruk bestaat uit nullen en zegt dus niets.")
    return [float(w) / lengte for w in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Hoeveel twee afdrukken op elkaar lijken: 1 is identiek, 0 is niets gemeen."""
    if len(left) != len(right):
        raise EmbeddingError(
            f"Afdrukken van verschillende lengte ({len(left)} en {len(right)}) zijn niet te "
            "vergelijken. Waarschijnlijk zijn ze met verschillende modellen gemaakt."
        )
    som = sum(a * b for a, b in zip(l2_normalize(left), l2_normalize(right), strict=True))
    # Afrondingsfouten kunnen net buiten het bereik uitkomen; dat is verwarrend in een antwoord.
    return max(-1.0, min(1.0, som))


@dataclass(frozen=True, slots=True)
class Candidate:
    """Eén ingeschreven stem, klaar om mee te vergelijken."""

    profile_id: int
    user_id: int
    embedding: Sequence[float]


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: bool
    confidence: float
    threshold: float
    user_id: int | None = None
    profile_id: int | None = None
    # Hoe dicht de op één na beste erbij zat. Liggen die vlak bij elkaar, dan is de uitslag
    # minder stellig dan het cijfer doet vermoeden.
    runner_up_confidence: float | None = None


def best_match(
    embedding: Sequence[float], candidates: Sequence[Candidate], *, threshold: float
) -> MatchResult:
    """Zoek de stem die er het meest op lijkt, of geef 'niet herkend' terug."""
    scores: list[tuple[float, Candidate]] = []
    for kandidaat in candidates:
        if len(kandidaat.embedding) != len(embedding):
            # Een afdruk van een ander model overslaan is beter dan de hele vergelijking
            # laten stranden; de rest kan nog prima kloppen.
            continue
        scores.append((cosine_similarity(embedding, kandidaat.embedding), kandidaat))

    if not scores:
        return MatchResult(matched=False, confidence=0.0, threshold=threshold)

    scores.sort(key=lambda paar: paar[0], reverse=True)
    beste_score, beste = scores[0]
    tweede = scores[1][0] if len(scores) > 1 else None

    if beste_score < threshold:
        return MatchResult(
            matched=False,
            confidence=beste_score,
            threshold=threshold,
            runner_up_confidence=tweede,
        )
    return MatchResult(
        matched=True,
        confidence=beste_score,
        threshold=threshold,
        user_id=beste.user_id,
        profile_id=beste.profile_id,
        runner_up_confidence=tweede,
    )
