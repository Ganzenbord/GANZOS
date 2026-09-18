"""Skills beheren en taken laten draaien."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import consume_confirmation, require_permission
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.permissions import tier_allows
from app.models.platform import MissionTask, Skill
from app.models.user import User
from app.schemas.skill import (
    ExecuteOut,
    MatchOut,
    SkillCreate,
    SkillOut,
    SkillUpdate,
    TaskCreate,
    TaskOut,
    ToolOut,
)
from app.services import skill_service, task_service
from app.services.skill_executor import SkillExecutor
from app.services.skill_matcher import SkillMatcher

logger = logging.getLogger("ganz.skills")

router = APIRouter(tags=["skills"])


def get_executor(request: Request) -> SkillExecutor:
    return request.app.state.skill_executor


def get_matcher(request: Request) -> SkillMatcher:
    return request.app.state.skill_matcher


async def _skill_van(session: AsyncSession, skill_id: int, user: User) -> Skill:
    skill = await session.get(Skill, skill_id)
    if skill is None or skill.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deze skill bestaat niet.")
    return skill


async def _taak_van(session: AsyncSession, task_id: int, user: User) -> MissionTask:
    taak = await session.get(MissionTask, task_id)
    if taak is None or taak.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deze taak bestaat niet.")
    return taak


# --- Skills ------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    user: User = Depends(require_permission("skills.read")),
    session: AsyncSession = Depends(get_session),
) -> list[SkillOut]:
    skills = await skill_service.list_skills(session, user.id)
    return [SkillOut.model_validate(s, from_attributes=True) for s in skills]


@router.get("/skills/tools", response_model=list[ToolOut])
async def list_tools(
    _user: User = Depends(require_permission("skills.read")),
    executor: SkillExecutor = Depends(get_executor),
) -> list[ToolOut]:
    """Waar een skill uit kan bestaan.

    `simulated: true` betekent: Ganz loopt de stap na en logt hem, maar doet nog niets in de
    buitenwereld.
    """
    return [
        ToolOut(
            name=t.name, description=t.description, sensitive=t.sensitive, simulated=t.simulated
        )
        for t in executor.registry.all()
    ]


@router.get("/skills/active", response_model=list[SkillOut])
async def list_active_skills(
    user: User = Depends(require_permission("skills.read")),
    session: AsyncSession = Depends(get_session),
) -> list[SkillOut]:
    """Alleen de skills die aanstaan, de meest gebruikte eerst.

    Staat met opzet vóór /skills/{skill_id} in dit bestand: FastAPI kijkt op volgorde, en
    "active" zou anders als skill-id gelezen worden.
    """
    skills = [s for s in await skill_service.list_skills(session, user.id) if s.enabled]
    skills.sort(key=lambda s: (-s.run_count, s.name))
    return [SkillOut.model_validate(s, from_attributes=True) for s in skills]


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreate,
    user: User = Depends(require_permission("skills.write")),
    session: AsyncSession = Depends(get_session),
    executor: SkillExecutor = Depends(get_executor),
) -> SkillOut:
    try:
        skill = await skill_service.create_skill(
            session, user_id=user.id, data=payload.model_dump(), executor=executor
        )
    except skill_service.SkillError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    await session.commit()
    return SkillOut.model_validate(skill, from_attributes=True)


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: int,
    payload: SkillUpdate,
    user: User = Depends(require_permission("skills.write")),
    session: AsyncSession = Depends(get_session),
    executor: SkillExecutor = Depends(get_executor),
) -> SkillOut:
    skill = await _skill_van(session, skill_id, user)
    try:
        skill = await skill_service.update_skill(
            session, skill=skill, data=payload.model_dump(exclude_unset=True), executor=executor
        )
    except skill_service.SkillError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    await session.commit()
    return SkillOut.model_validate(skill, from_attributes=True)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: int,
    user: User = Depends(require_permission("skills.write")),
    session: AsyncSession = Depends(get_session),
):
    skill = await _skill_van(session, skill_id, user)
    await skill_service.delete_skill(session, skill=skill)
    await session.commit()


# --- Taken -------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    user: User = Depends(require_permission("tasks.read")),
    session: AsyncSession = Depends(get_session),
) -> list[TaskOut]:
    from sqlalchemy import select

    rijen = await session.scalars(
        select(MissionTask)
        .where(MissionTask.user_id == user.id)
        .order_by(MissionTask.created_at.desc())
    )
    return [TaskOut.model_validate(t, from_attributes=True) for t in rijen]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    user: User = Depends(require_permission("tasks.write")),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    taak = await task_service.create_task(
        session, user_id=user.id, title=payload.title, description=payload.description
    )
    await session.commit()
    return TaskOut.model_validate(taak, from_attributes=True)


@router.post("/tasks/{task_id}/match", response_model=MatchOut)
async def match_task(
    task_id: int,
    user: User = Depends(require_permission("tasks.write")),
    session: AsyncSession = Depends(get_session),
    matcher: SkillMatcher = Depends(get_matcher),
    settings: Settings = Depends(get_settings),
) -> MatchOut:
    """Zoek de skill die bij deze taak hoort.

    Ook als er niets past krijg je een antwoord met uitleg — dat is het moment waarop je
    besluit een skill te maken.
    """
    taak = await _taak_van(session, task_id, user)
    try:
        uitslag = await task_service.match_task(
            session, task=taak, matcher=matcher, threshold=settings.skill_match_threshold
        )
    except task_service.TaskError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    await session.commit()
    return MatchOut(
        matched=uitslag.matched,
        confidence=uitslag.confidence,
        threshold=uitslag.threshold,
        reason=uitslag.reason,
        backend=uitslag.backend,
        skill=SkillOut.model_validate(uitslag.skill, from_attributes=True) if uitslag.skill else None,
        task=TaskOut.model_validate(taak, from_attributes=True),
    )


@router.post("/tasks/{task_id}/execute", response_model=ExecuteOut)
async def execute_task(
    task_id: int,
    request: Request,
    user: User = Depends(require_permission("tasks.execute")),
    session: AsyncSession = Depends(get_session),
    executor: SkillExecutor = Depends(get_executor),
) -> ExecuteOut:
    """Voer de gekozen skill uit.

    Of er bevestigd moet worden, hangt niet aan dit endpoint maar aan de stappen: één skill
    haalt het weer op, de volgende publiceert een video. Zit er gevoelig gereedschap bij, dan
    vraagt de skill bovendien om het recht dat erbij hoort. Die twee zijn niet hetzelfde: het
    recht zegt of je het mág, de bevestiging of je het nú wilt.
    """
    taak = await _taak_van(session, task_id, user)

    gevoelig: list[str] = []
    if taak.skill_id is not None:
        skill = await session.get(Skill, taak.skill_id)
        if skill is not None:
            nodig = task_service.required_permission_for(skill, executor)
            if nodig and not tier_allows(user.tier, nodig):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"Skill '{skill.name}' vraagt het recht '{nodig}', en dat heb je niet.",
                )
            gevoelig = executor.sensitive_tools(list(skill.steps or []))

    bevestigd = await consume_confirmation(
        request,
        user=user,
        session=session,
        permission_key="tasks.execute",
        required=bool(gevoelig),
    )
    try:
        uitkomst = await task_service.execute_task(
            session, task=taak, executor=executor, confirmed=bevestigd
        )
    except task_service.TaskError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    await session.commit()
    return ExecuteOut(
        ok=uitkomst.ok,
        task=TaskOut.model_validate(taak, from_attributes=True),
        steps=uitkomst.steps,
        error=uitkomst.error,
    )


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: int,
    user: User = Depends(require_permission("tasks.write")),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    taak = await _taak_van(session, task_id, user)
    try:
        await task_service.cancel_task(session, task=taak)
    except task_service.TaskError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    await session.commit()
    return TaskOut.model_validate(taak, from_attributes=True)
