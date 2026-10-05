"""Wie er in het lab werkt.

Drie van de zes zijn pure code en mogen dus nooit een model aanroepen: de Scout haalt
data op, de Screener beslist op regels, en de Risk Officer heeft een absoluut veto. Een
veto dat van een antwoord van buiten afhangt, is geen veto.

De namen zijn Engels (het zijn identifiers en ze komen in logs terug); wat ze doen staat
in het Nederlands in de uitleg hieronder.
"""

from __future__ import annotations

from enum import StrEnum


class QuantAgent(StrEnum):
    SCOUT = "scout"
    SCREENER = "screener"
    CLASSIFIER = "classifier"
    ANALYST = "analyst"
    RISK_OFFICER = "risk_officer"
    REVIEWER = "reviewer"


AGENT_UITLEG: dict[QuantAgent, str] = {
    QuantAgent.SCOUT: "Haalt marktgegevens op en schrijft ze onveranderd weg. Pure code.",
    QuantAgent.SCREENER: "Past de filters van een hypothese toe en beslist. Pure code.",
    QuantAgent.CLASSIFIER: "Geeft een score aan een kandidaat. Mag alleen scores geven.",
    QuantAgent.ANALYST: "Geeft gestructureerd advies. Heeft geen gereedschap en geen netwerk.",
    QuantAgent.RISK_OFFICER: "Blokkeert wat buiten de grenzen valt. Pure code, absoluut veto.",
    QuantAgent.REVIEWER: "Leest mee en doet voorstellen. Verandert zelf nooit iets.",
}

# Agents die uitsluitend uit code bestaan. Hier staat geen budget tegenover, en een
# aanroep van een taalmodel namens een van deze drie is per definitie een fout.
CODE_ONLY_AGENTS: frozenset[QuantAgent] = frozenset(
    {QuantAgent.SCOUT, QuantAgent.SCREENER, QuantAgent.RISK_OFFICER}
)
