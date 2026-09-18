"""Het rechtenregister.

Eén lijst met alle rechten, zodat je in één oogopslag ziet wie wat mag. Tier 1 is de
eigenaar; hoe hoger het tiernummer, hoe minder rechten. Een gebruiker mag een recht
als zijn tier kleiner of gelijk is aan `max_tier`.

Zonder tier (`None`) mag je niets. Dat is met opzet geen aparte reeks if-jes in de
endpoints: het zit hier, in `tier_allows`, zodat het overal op dezelfde manier uitpakt.

`sensitive` betekent: deze handeling vraagt een tweede bevestiging met het wachtwoord
voordat hij wordt uitgevoerd.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.models.user import TIER_GUEST, TIER_LIMITED, TIER_OWNER, TIER_TRUSTED


@dataclass(frozen=True)
class Permission:
    key: str
    description: str
    max_tier: int
    sensitive: bool = False


PERMISSIONS: tuple[Permission, ...] = (
    Permission("core.read", "Ganz Core en de status bekijken", TIER_GUEST),
    Permission("system.read", "Systeemmonitor bekijken", TIER_LIMITED),
    # De ruwe metingen (belasting, schijfruimte, hoe lang de machine al draait) zeggen
    # meer over de computer dan het stoplicht op het dashboard. Alleen voor tier 1.
    Permission("system.admin", "Systeemmetingen in detail bekijken", TIER_OWNER),
    Permission("activity.read", "Activiteitenlog bekijken", TIER_TRUSTED),
    Permission("skills.read", "Skills bekijken", TIER_LIMITED),
    Permission("skills.write", "Skills maken, wijzigen en verwijderen", TIER_TRUSTED),
    Permission("tasks.read", "Missies en taken bekijken", TIER_LIMITED),
    Permission("tasks.write", "Taken aanmaken en annuleren", TIER_TRUSTED),
    # Uitvoeren is iets anders dan aanmaken: hier gaat Ganz echt iets doen.
    Permission("tasks.execute", "Een taak laten uitvoeren", TIER_TRUSTED),
    Permission("memory.read", "Geheugen bekijken", TIER_TRUSTED),
    Permission("conversations.read", "Gesprekken bekijken", TIER_TRUSTED),
    Permission("workflows.read", "Workflows bekijken", TIER_TRUSTED),
    Permission("integrations.read", "Integraties bekijken", TIER_TRUSTED),
    Permission("integrations.manage", "Integraties koppelen of loskoppelen", TIER_OWNER, True),
    # Stem: herkennen kan zonder recht (dat ís de herkenning), de rest niet.
    Permission("voice.read", "Ingeschreven stemmen bekijken", TIER_TRUSTED),
    Permission("voice.enroll", "Een stem inschrijven en zo toegang uitdelen", TIER_OWNER, True),
    Permission("voice.delete", "Een ingeschreven stem weghalen", TIER_OWNER, True),
    # To-do
    Permission("todo.read", "Dagelijkse takenlijst bekijken", TIER_LIMITED),
    Permission("todo.write", "Taken maken, wijzigen en afvinken", TIER_TRUSTED),
    # Finance: gevoelig, dus alleen de eigenaar.
    Permission("finance.read", "Financieel overzicht bekijken", TIER_OWNER),
    Permission("finance.manage", "Financiële accounts koppelen of wijzigen", TIER_OWNER, True),
    # Social
    Permission("social.read", "Social-statistieken bekijken", TIER_LIMITED),
    Permission("social.manage", "Kanalen koppelen of verwijderen", TIER_TRUSTED, True),
    # Uploads
    Permission("upload.read", "Uploadschema bekijken", TIER_LIMITED),
    Permission("upload.schedule", "Uploads inplannen of wijzigen", TIER_TRUSTED),
    Permission("upload.execute", "Een upload nu uitvoeren", TIER_OWNER, True),
)

PERMISSION_MAP: dict[str, Permission] = {perm.key: perm for perm in PERMISSIONS}


def get_permission(key: str) -> Permission:
    try:
        return PERMISSION_MAP[key]
    except KeyError as exc:  # pragma: no cover - programmeerfout
        raise KeyError(f"Onbekend recht: {key}") from exc


def tier_allows(tier: int | None, key: str) -> bool:
    if tier is None:
        return False
    return tier <= get_permission(key).max_tier


def permissions_for_tier(tier: int | None) -> list[str]:
    """Wat deze tier mag, zónder de uitzonderingen per persoon."""
    if tier is None:
        return []
    return [perm.key for perm in PERMISSIONS if tier <= perm.max_tier]


def allows(tier: int | None, key: str, overrides: Mapping[str, bool] | None = None) -> bool:
    """Mag deze persoon dit?

    De tier bepaalt de grondlijn, een uitzondering per persoon gaat daaroverheen — in
    allebei de richtingen. Zonder die uitzonderingen zou "mag alleen de lampen, de mail en
    het weer" niet te maken zijn: een tier is een rechte lijn, en zo iemand moet een greep
    eruit hebben. En andersom: iemand die verder alles mag maar dit ene ding niet.

    Let op wat `tier is None` nu betekent: geen rechten uit een tier. Heeft zo iemand ook
    geen uitzonderingen, dan mag hij nog steeds niets — precies zoals eerst.
    """
    if overrides:
        uitzondering = overrides.get(key)
        if uitzondering is not None:
            # Een recht dat niet bestaat is geen recht, ook niet als iemand het toekent.
            get_permission(key)
            return uitzondering
    return tier_allows(tier, key)


def effective_permissions(
    tier: int | None, overrides: Mapping[str, bool] | None = None
) -> list[str]:
    """Alles wat deze persoon werkelijk mag. De frontend verbergt hiermee wat toch niet werkt.

    Dit is wat `/auth/me` teruggeeft, en het is het enige antwoord dat klopt: kijken naar
    alleen de tier laat de uitzonderingen weg.
    """
    return [perm.key for perm in PERMISSIONS if allows(tier, perm.key, overrides)]
