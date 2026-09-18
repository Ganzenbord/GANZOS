"""Het pad dat een taak aflegt.

    opdracht → planned → matching → (skill gevonden?)
                                     ├── ja  → running → done | failed
                                     └── nee → planned, met uitleg waarom niet

Alles wat onderweg besloten wordt, komt in de taak te staan: welke skill het werd, hoe zeker
dat was, en waarom. Zonder die uitleg is een verkeerde match niet na te trekken — en dat is
precies het moment waarop je hem nodig hebt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityAction
from app.models.platform import FINAL_STATUSES, MissionStatus, MissionTask, Skill
from app.services.activity_service import log_activity
from app.services.skill_executor import ExecutionResult, SkillExecutor, StepContext, StepError
from app.services.skill_matcher import SkillMatch, SkillMatcher

logger = logging.getLogger("ganz.tasks")


class TaskError(Exception):
    """Gaat mis op een manier die de gebruiker moet weten."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_task(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    description: str | None = None,
    source: str = "api",
) -> MissionTask:
    taak = MissionTask(
        user_id=user_id,
        title=title,
        description=description,
        status=MissionStatus.PLANNED,
        source=source,
    )
    session.add(taak)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.TASK_CREATED,
        user_id=user_id,
        message=f"Taak aangemaakt: {title}",
        subject_type="mission_task",
        subject_id=taak.id,
    )
    return taak


async def active_skills(session: AsyncSession, user_id: int) -> list[Skill]:
    rijen = await session.scalars(
        select(Skill).where(Skill.user_id == user_id, Skill.enabled.is_(True)).order_by(Skill.name)
    )
    return list(rijen)


async def match_task(
    session: AsyncSession,
    *,
    task: MissionTask,
    matcher: SkillMatcher,
    threshold: float,
) -> SkillMatch:
    """Zoek de skill die bij deze taak hoort en leg de uitkomst vast.

    Ook als er niets past. Juist dan: "Ganz deed niets" zonder uitleg is het vervelendste
    soort stilte.
    """
    if task.status in FINAL_STATUSES:
        raise TaskError("taak_is_klaar", f"Deze taak is al {task.status}.")

    task.status = MissionStatus.MATCHING
    await session.flush()

    opdracht = " ".join(deel for deel in (task.title, task.description) if deel)
    uitslag = await matcher.match(opdracht, await active_skills(session, task.user_id), threshold=threshold)

    task.match_confidence = uitslag.confidence
    task.match_reason = f"[{uitslag.backend}] {uitslag.reason}"
    task.skill_id = uitslag.skill.id if uitslag.skill else None
    # Geen match betekent terug naar 'planned': de taak blijft bestaan, er is alleen nog geen
    # skill voor. Dat is het moment waarop je er een maakt.
    task.status = MissionStatus.PLANNED
    await session.flush()

    await log_activity(
        session,
        action=ActivityAction.TASK_MATCHED if uitslag.matched else ActivityAction.TASK_UNMATCHED,
        user_id=task.user_id,
        message=(
            f"Skill gekozen voor '{task.title}': {uitslag.reason}"
            if uitslag.matched
            else f"Geen skill voor '{task.title}': {uitslag.reason}"
        ),
        subject_type="mission_task",
        subject_id=task.id,
        context={"confidence": uitslag.confidence, "backend": uitslag.backend},
    )
    return uitslag


async def execute_task(
    session: AsyncSession,
    *,
    task: MissionTask,
    executor: SkillExecutor,
    confirmed: bool,
) -> ExecutionResult:
    """Voer de gekozen skill uit. De taak moet al gematcht zijn."""
    if task.status in FINAL_STATUSES:
        raise TaskError("taak_is_klaar", f"Deze taak is al {task.status}.")
    if task.skill_id is None:
        raise TaskError(
            "geen_skill",
            "Er is nog geen skill aan deze taak gekoppeld. Laat hem eerst matchen "
            "(POST /api/tasks/{id}/match).",
        )

    skill = await session.get(Skill, task.skill_id)
    if skill is None:
        raise TaskError("skill_weg", "De gekoppelde skill bestaat niet meer.")
    if not skill.enabled:
        raise TaskError("skill_uit", f"Skill '{skill.name}' staat uit.")

    task.status = MissionStatus.RUNNING
    task.started_at = _now()
    task.error = None
    await session.flush()

    uitkomst = await executor.run(
        list(skill.steps or []),
        StepContext(
            user_id=task.user_id,
            task_id=task.id,
            skill_name=skill.name,
            step_index=0,
            confirmed=confirmed,
            session=session,
        ),
    )

    skill.run_count += 1
    skill.last_used_at = _now()

    if uitkomst.ok:
        task.status = MissionStatus.DONE
        task.completed_at = _now()
        # "Is dit echt gebeurd?" is geen eigenschap van de taak maar van de stappen. Zolang
        # het één vaste True was, meldde Ganz een echte upload als een oefening.
        task.result = {
            "steps": uitkomst.steps,
            "simulated": all(stap.get("simulated", True) for stap in uitkomst.steps),
        }
        skill.success_count += 1
    else:
        # Wachten op een bevestiging is geen mislukking: de taak blijft staan tot iemand
        # bevestigt. Alleen een echte fout telt mee als mislukking van de skill.
        wacht = uitkomst.error is not None and "bevestig" in uitkomst.error.lower()
        task.status = MissionStatus.WAITING if wacht else MissionStatus.FAILED
        task.error = uitkomst.error
        task.result = {"steps": uitkomst.steps, "failed_step": uitkomst.failed_step}
        if wacht:
            skill.run_count -= 1  # dit telde nog niet als een echte poging
        else:
            task.completed_at = _now()
            skill.failure_count += 1

    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.TASK_COMPLETED if uitkomst.ok else ActivityAction.TASK_FAILED,
        user_id=task.user_id,
        message=(
            f"Taak '{task.title}' uitgevoerd met skill '{skill.name}'."
            if uitkomst.ok
            else f"Taak '{task.title}' niet uitgevoerd: {uitkomst.error}"
        ),
        subject_type="mission_task",
        subject_id=task.id,
        context={"skill": skill.name, "skill_version": skill.version},
    )
    return uitkomst


async def cancel_task(session: AsyncSession, *, task: MissionTask) -> MissionTask:
    if task.status in FINAL_STATUSES:
        raise TaskError("taak_is_klaar", f"Deze taak is al {task.status}.")
    task.status = MissionStatus.CANCELLED
    task.completed_at = _now()
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.TASK_CANCELLED,
        user_id=task.user_id,
        message=f"Taak '{task.title}' geannuleerd.",
        subject_type="mission_task",
        subject_id=task.id,
    )
    return task


def required_permission_for(skill: Skill, executor: SkillExecutor) -> str | None:
    """Welk recht deze skill nodig heeft.

    Staat het op de skill zelf, dan geldt dat. Anders: zodra er gevoelig gereedschap in de
    stappen zit, is `upload.execute` het minimum — dat is het zwaarste recht dat we hebben
    voor "iets doen dat naar buiten gaat".
    """
    if skill.required_permission:
        return skill.required_permission
    try:
        if executor.sensitive_tools(list(skill.steps or [])):
            return "upload.execute"
    except StepError:
        return None
    return None
