"""Skills beheren.

Weinig regels, maar wel twee die ertoe doen: de stappen worden nagekeken vóór ze worden
opgeslagen, en het versienummer loopt op zodra ze veranderen. Dat laatste is wat je nodig
hebt als je in het logboek wilt zien wélke versie draaide toen iets misging.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityAction
from app.models.platform import Skill
from app.services.activity_service import log_activity
from app.services.skill_executor import SkillExecutor, StepError


class SkillError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def list_skills(session: AsyncSession, user_id: int) -> list[Skill]:
    rijen = await session.scalars(
        select(Skill).where(Skill.user_id == user_id).order_by(Skill.name)
    )
    return list(rijen)


async def create_skill(
    session: AsyncSession, *, user_id: int, data: dict[str, Any], executor: SkillExecutor
) -> Skill:
    stappen = list(data.get("steps") or [])
    _controleer_stappen(stappen, executor)

    skill = Skill(user_id=user_id, version=1, **{**data, "steps": stappen})
    session.add(skill)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SKILL_CREATED,
        user_id=user_id,
        message=f"Skill '{skill.name}' aangemaakt.",
        subject_type="skill",
        subject_id=skill.id,
    )
    return skill


async def update_skill(
    session: AsyncSession, *, skill: Skill, data: dict[str, Any], executor: SkillExecutor
) -> Skill:
    if "steps" in data and data["steps"] is not None:
        stappen = list(data["steps"])
        _controleer_stappen(stappen, executor)
        if stappen != list(skill.steps or []):
            # Alleen bij écht andere stappen; een naamswijziging is geen nieuwe versie.
            skill.version += 1
        data = {**data, "steps": stappen}

    for veld, waarde in data.items():
        if waarde is not None:
            setattr(skill, veld, waarde)

    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SKILL_UPDATED,
        user_id=skill.user_id,
        message=f"Skill '{skill.name}' gewijzigd (versie {skill.version}).",
        subject_type="skill",
        subject_id=skill.id,
    )
    return skill


async def delete_skill(session: AsyncSession, *, skill: Skill) -> None:
    naam, user_id, skill_id = skill.name, skill.user_id, skill.id
    await session.delete(skill)
    await log_activity(
        session,
        action=ActivityAction.SKILL_DELETED,
        user_id=user_id,
        message=f"Skill '{naam}' verwijderd.",
        subject_type="skill",
        subject_id=skill_id,
    )


def _controleer_stappen(stappen: list[dict[str, Any]], executor: SkillExecutor) -> None:
    """Een skill met een onuitvoerbare stap hoort niet opgeslagen te kunnen worden.

    Anders merk je het pas als iemand hem aanroept, en dan staat de taak al op 'running'.
    """
    try:
        executor.validate(stappen)
    except StepError as exc:
        raise SkillError("stappen_ongeldig", str(exc)) from exc
