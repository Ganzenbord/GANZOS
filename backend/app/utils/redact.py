"""Eén plek die bepaalt wat gevoelig is.

Het activiteitenlog schoonde zijn context al, maar dat was de enige plek. Een stack trace
in `ganz.log`, een foutmelding die naar de client gaat of een regel die een
bewakingsdienst opslurpt liepen daar helemaal omheen — terwijl daar precies dezelfde
dingen in kunnen staan.

Dus staat het patroon hier, en gebruiken het logboek, de logging en de foutafhandeling
allemaal dít. Wordt er een nieuw soort geheim bedacht, dan is er één regel om aan te passen.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Sleutelnamen die nooit een waarde mogen tonen. Ruim genomen: liever een keer te veel
# "[verwijderd]" in een logregel dan één keer een token dat je kwijt bent.
FORBIDDEN_KEY = re.compile(
    r"(token|secret|password|passwd|pin|api[_-]?key|credential|client[_-]?secret"
    r"|refresh|access[_-]?token|authorization|cookie|session"
    r"|iban|bsn|account[_-]?number|balance|saldo"
    r"|value|amount|revenue|total|vermogen)",
    re.IGNORECASE,
)

# Waarden die er in vrije tekst uitzien als een geheim, ook zonder sleutelnaam ernaast.
# Een stack trace bevat geen `{"token": ...}` maar wel de waarde zelf.
_LOOKS_LIKE_SECRET = (
    # Bearer-tokens en JWT's: drie stukken base64 met punten ertussen.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    # Fernet-sleutels en vergelijkbare lange url-safe brokken.
    re.compile(r"\bg[A-Za-z0-9_\-]{42,}=*\b"),
    # Google-API-sleutels.
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    # OAuth-clientsecrets van Google.
    re.compile(r"\bGOCSPX-[0-9A-Za-z_\-]{10,}\b"),
    # Een databaseverbinding met wachtwoord erin.
    re.compile(r"(?<=://)[^:/\s]+:[^@/\s]+(?=@)"),
)

REDACTED = "[verwijderd]"
MAX_DEPTH = 4


def scrub(value: Any, depth: int = 0) -> Any:
    """Haalt gevoelige velden uit een willekeurige structuur.

    Gaat op de sleutelnaam af, niet op de inhoud: `{"api_key": "abc"}` is verdacht door de
    naam, en wat erin staat doet er niet toe.
    """
    if depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (REDACTED if FORBIDDEN_KEY.search(str(key)) else scrub(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(item, depth + 1) for item in value]
    return value


def redact_text(tekst: str) -> str:
    """Haalt uit vrije tekst weg wat eruitziet als een geheim.

    Voor stack traces en logregels: daar staat geen nette structuur in, alleen tekst waar
    een token zomaar middenin kan staan.
    """
    for patroon in _LOOKS_LIKE_SECRET:
        tekst = patroon.sub(REDACTED, tekst)
    return tekst


class SecretFilter(logging.Filter):
    """Haalt geheimen uit elke logregel, van welke bibliotheek hij ook komt.

    Als filter en niet als formatter: een formatter geldt per handler, en de eerste keer dat
    iemand een tweede handler toevoegt — een bestand erbij, een bewakingsdienst — is die
    nieuwe handler ongefilterd. Dit hangt aan de logger zelf.

    Let op wat dit niet kan: het ziet alleen de tekst. Een geheim dat niet op een geheim
    lijkt, glipt erdoor. Daarom is het de tweede verdedigingslinie; de eerste is niet loggen.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_text(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in record.args
                )
        return True
