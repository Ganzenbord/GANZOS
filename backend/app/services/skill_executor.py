"""Het uitvoeren van de stappen van een skill.

De uitvoering is nu nog een stub: de stappen worden nagelopen, gecontroleerd en gelogd,
maar er gebeurt niets in de buitenwereld. Dat is met opzet — een halve upload is erger dan
geen upload.

Wat hier wél al goed staat, is het koppelvlak. Een gereedschap is een naam plus een functie
die een stap uitvoert, en die worden in een `ToolRegistry` gezet. Straks een echte YouTube-
upload aansluiten betekent: één `register()` erbij. De Task-API, de statussen en de manier
waarop resultaten worden opgeslagen veranderen daar niet van.

Twee dingen die het koppelvlak nu al afdwingt, omdat ze later niet meer in te bouwen zijn
zonder alles om te gooien:

- **Een gereedschap zegt zelf of het gevoelig is.** Is het dat, dan weigert de uitvoering
  zonder bevestiging — ook al is de stap al begonnen.
- **Een stap die een onbekend gereedschap noemt, laat de hele taak falen** voordat er iets
  is gedaan. Half uitgevoerde skills zijn niet terug te draaien.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - alleen voor de typecontrole
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("ganz.skills")


class StepError(Exception):
    """Een stap kan niet (veilig) worden uitgevoerd. De tekst is voor de gebruiker."""


@dataclass(frozen=True, slots=True)
class StepContext:
    """Wat een gereedschap over de taak mag weten."""

    user_id: int
    task_id: int
    skill_name: str
    step_index: int
    confirmed: bool
    # De lopende databasesessie. Gesimuleerd gereedschap heeft hem niet nodig; echt
    # gereedschap wel, want dat moet een koppeling opzoeken en zijn werk vastleggen. Hij
    # staat hier en niet in de constructor van de uitvoerder: een sessie hoort bij één
    # verzoek, de uitvoerder gaat de hele looptijd van Ganz mee.
    session: "AsyncSession | None" = None


# Een gereedschap krijgt de stap en de context, en geeft terug wat het deed.
ToolCallable = Callable[[dict[str, Any], StepContext], Awaitable[dict[str, Any]]]

# Kijkt of de stap de gegevens bevat die dit gereedschap nodig heeft, en gooit anders een
# StepError. Draait bij het opslaan van een skill, dus lang voor het uitvoeren.
StepCheck = Callable[[dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    handler: ToolCallable
    # Gevoelig gereedschap draait alleen met een bevestigde handeling. Denk aan publiceren,
    # geld, of iets wat niet terug te draaien is.
    sensitive: bool = False
    # Zolang dit True is, doet het gereedschap alsof. Gaat per gereedschap uit zodra de
    # echte koppeling er staat — niet in één keer voor alles.
    simulated: bool = True
    # Controleert of een stap compleet is. Zonder dit merk je pas tijdens het uitvoeren dat
    # er een titel ontbreekt, en dan staat de taak al op "bezig".
    check: StepCheck | None = None


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Gereedschap '{tool.name}' staat al in het register.")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise StepError(
                f"Onbekend gereedschap '{name}'. Beschikbaar: "
                f"{', '.join(sorted(self._tools)) or 'nog niets'}."
            ) from None

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


@dataclass(slots=True)
class ExecutionResult:
    ok: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # Welke stap het misging, zodat je weet waar je verder moet kijken.
    failed_step: int | None = None


async def _simulate(step: dict[str, Any], context: StepContext) -> dict[str, Any]:
    """Wat een gereedschap doet zolang de echte koppeling er nog niet is."""
    return {
        "simulated": True,
        "note": "Nog niet echt uitgevoerd; de koppeling bestaat nog niet.",
        "params": {k: v for k, v in step.items() if k not in {"tool", "action"}},
    }


def _check_youtube_upload(step: dict[str, Any]) -> None:
    """Een uploadstap zonder bestand of titel is geen uploadstap.

    Dit draait al bij het opslaan van de skill. Zou het pas bij het uitvoeren gebeuren, dan
    ontdek je de ontbrekende titel nadat je hebt bevestigd dat er gepubliceerd mag worden.
    """
    if not str(step.get("file") or "").strip():
        raise StepError("noemt geen bestand ('file')")
    if not str(step.get("title") or "").strip():
        raise StepError("noemt geen titel ('title')")
    tags = step.get("tags")
    if tags is not None and not isinstance(tags, list):
        raise StepError("'tags' moet een lijst zijn")
    privacy = step.get("privacy")
    if privacy is not None and privacy not in {"private", "unlisted", "public"}:
        raise StepError("'privacy' kan alleen private, unlisted of public zijn")


async def _youtube_upload(step: dict[str, Any], context: StepContext) -> dict[str, Any]:
    """Publiceert echt een video. Het eerste gereedschap dat niet doet alsof.

    Wat een stap meegeeft: `file` (een bestandsnaam in de ingestelde videomap), `title`, en
    optioneel `description`, `tags` en `privacy`. Het pad wordt niet hier maar in
    `youtube_service` nagelopen — daar staat ook waarom dat niet zomaar elk pad mag zijn.
    """
    # Binnen de functie: zo hangt het opstarten van Ganz niet aan de YouTube-koppeling, en
    # blijft dit bestand leesbaar als lijst van wat Ganz kan.
    from app.services import youtube_service

    if context.session is None:  # pragma: no cover - alleen bij verkeerd gebruik
        raise StepError(
            "Deze stap heeft een databasesessie nodig en kreeg er geen. Dit is een fout in "
            "Ganz zelf, niet in je skill."
        )

    _check_youtube_upload(step)
    bestand = str(step["file"]).strip()
    titel = str(step["title"]).strip()

    rauwe_tags = step.get("tags") or []
    tags = [str(t) for t in rauwe_tags] if isinstance(rauwe_tags, list) else []

    try:
        video = await youtube_service.upload(
            context.session,
            context.user_id,
            file_name=bestand,
            title=titel,
            description=str(step.get("description") or ""),
            tags=tags,
            privacy=step.get("privacy"),
        )
    except youtube_service.YouTubeError as exc:
        raise StepError(exc.message) from exc

    return {
        "simulated": False,
        "video_id": video.external_id,
        "url": video.url,
        "privacy": video.privacy,
    }


def default_registry() -> ToolRegistry:
    """De gereedschappen die Ganz kent.

    Alles is nog gesimuleerd behalve `youtube.upload`: die publiceert echt. Dat staat per
    gereedschap aan en niet in één keer voor alles — een gereedschap gaat pas van "doet
    alsof" naar "doet het" als de koppeling eronder er echt is.

    De namen komen overeen met de rechten uit `app/core/permissions.py` waar die bestaan,
    zodat een skill die `youtube.upload` gebruikt ook het recht `upload.execute` nodig heeft.
    Dat verband leggen we bij het uitvoeren, niet hier.
    """
    return ToolRegistry(
        [
            Tool("activity.log", "Een regel in het activiteitenlog zetten", _simulate),
            Tool("todo.create", "Een taak op de dagelijkse lijst zetten", _simulate),
            Tool("weather.read", "Het weerbericht opvragen", _simulate),
            Tool("calendar.read", "De agenda bekijken", _simulate),
            Tool("mail.read", "Binnengekomen mail lezen", _simulate),
            Tool("mail.send", "Mail versturen", _simulate, sensitive=True),
            Tool("smart_home.control", "Lampen en apparaten bedienen", _simulate),
            Tool(
                "youtube.upload",
                "Een video publiceren naar YouTube",
                _youtube_upload,
                sensitive=True,
                simulated=False,
                check=_check_youtube_upload,
            ),
            Tool("finance.read", "Het financieel overzicht opvragen", _simulate),
        ]
    )


class SkillExecutor:
    """Loopt de stappen van een skill langs.

    De uitvoering stopt bij de eerste stap die misgaat. Er wordt niets teruggedraaid — dat
    kan pas zinnig als de gereedschappen echt iets doen en zelf weten hoe ze dat ongedaan
    maken. Tot die tijd is stoppen het eerlijkste antwoord, en staat in het resultaat precies
    welke stappen wél gelukt zijn.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or default_registry()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def validate(self, steps: list[dict[str, Any]]) -> None:
        """Kijk vooraf of alle stappen uitvoerbaar zijn.

        Liever hier struikelen dan halverwege: bij stap drie stoppen laat een halve
        handeling achter die niemand heeft aangevraagd.
        """
        if not steps:
            raise StepError("Deze skill heeft geen stappen.")
        for nummer, stap in enumerate(steps, start=1):
            if not isinstance(stap, dict):
                raise StepError(f"Stap {nummer} is geen object met een 'tool' erin.")
            naam = stap.get("tool")
            if not naam:
                raise StepError(f"Stap {nummer} noemt geen gereedschap ('tool').")
            tool = self._registry.get(str(naam))
            if tool.check is not None:
                try:
                    tool.check(stap)
                except StepError as exc:
                    raise StepError(f"Stap {nummer} ({tool.name}): {exc}") from exc

    def sensitive_tools(self, steps: list[dict[str, Any]]) -> list[str]:
        """Welke stappen om een bevestiging vragen."""
        namen = []
        for stap in steps:
            naam = str(stap.get("tool", ""))
            if naam in self._registry and self._registry.get(naam).sensitive:
                namen.append(naam)
        return namen

    async def run(
        self, steps: list[dict[str, Any]], context: StepContext
    ) -> ExecutionResult:
        try:
            self.validate(steps)
        except StepError as exc:
            return ExecutionResult(ok=False, error=str(exc), failed_step=None)

        gedaan: list[dict[str, Any]] = []
        for nummer, stap in enumerate(steps, start=1):
            tool = self._registry.get(str(stap["tool"]))
            stap_context = StepContext(
                user_id=context.user_id,
                task_id=context.task_id,
                skill_name=context.skill_name,
                step_index=nummer,
                confirmed=context.confirmed,
                session=context.session,
            )

            if tool.sensitive and not context.confirmed:
                fout = (
                    f"Stap {nummer} ({tool.name}) is een gevoelige handeling en vraagt een "
                    "bevestiging. Bevestig eerst via POST /api/auth/confirm."
                )
                return ExecutionResult(ok=False, steps=gedaan, error=fout, failed_step=nummer)

            try:
                uitkomst = await tool.handler(stap, stap_context)
            except StepError as exc:
                return ExecutionResult(ok=False, steps=gedaan, error=str(exc), failed_step=nummer)
            except Exception as exc:  # noqa: BLE001 - één stuk gereedschap mag Ganz niet slopen
                logger.exception("Stap %s (%s) ging onverwacht mis", nummer, tool.name)
                return ExecutionResult(
                    ok=False,
                    steps=gedaan,
                    error=f"Stap {nummer} ({tool.name}) ging mis: {exc}",
                    failed_step=nummer,
                )

            gedaan.append(
                {
                    "step": nummer,
                    "tool": tool.name,
                    "action": stap.get("action"),
                    "simulated": tool.simulated,
                    "result": uitkomst,
                }
            )

        return ExecutionResult(ok=True, steps=gedaan)
