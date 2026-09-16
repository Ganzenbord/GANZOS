"""De to-do API.

Alle mutaties komen in het activiteitenlog. Alleen taken van de ingelogde gebruiker
zijn zichtbaar; de service geeft voor "bestaat niet" en "niet van jou" dezelfde fout.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.deps import require_permission
from app.models.activity import ActivityAction
from app.models.user import User
from app.schemas.todo import (
    CompletionIn,
    CompletionOut,
    HistoryOut,
    ReorderIn,
    SubtaskIn,
    SubtaskOut,
    SubtaskPatch,
    TodoDayOut,
    TodoTaskIn,
    TodoTaskOut,
    TodoTaskPatch,
)
from app.services import todo_service
from app.services.activity_service import log_activity
from app.services.todo_service import TodoNotFound

router = APIRouter(prefix="/todos", tags=["todo"])

read_access = require_permission("todo.read")
write_access = require_permission("todo.write")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Deze taak bestaat niet")


@router.get("/today", response_model=TodoDayOut)
async def todos_today(
    day: date | None = Query(default=None, description="Standaard vandaag"),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    return await todo_service.get_day(session, user.id, day or date.today())


@router.get("", response_model=list[TodoTaskOut])
async def list_todos(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    return list(await todo_service.list_tasks(session, user.id))


@router.post("", response_model=TodoTaskOut, status_code=status.HTTP_201_CREATED)
async def create_todo(
    payload: TodoTaskIn,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    data = payload.model_dump(exclude_unset=False)
    data["subtasks"] = [sub.model_dump() for sub in payload.subtasks]
    task = await todo_service.create_task(session, user.id, data)
    await log_activity(
        session,
        action=ActivityAction.TODO_CREATED,
        user_id=user.id,
        message=f"Taak '{task.title}' toegevoegd.",
        subject_type="todo_task",
        subject_id=task.id,
    )
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_todos(
    payload: ReorderIn,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await todo_service.reorder(session, user.id, payload.order)
    except TodoNotFound:
        raise NOT_FOUND from None
    await session.commit()


# Let op de volgorde: dit pad moet vóór /{task_id} staan, anders probeert FastAPI
# "subtasks" als taaknummer te lezen.
@router.patch("/subtasks/{subtask_id}", response_model=SubtaskOut)
async def update_subtask(
    subtask_id: int,
    payload: SubtaskPatch,
    day: date | None = Query(default=None),
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        subtask = await todo_service.update_subtask(
            session,
            user.id,
            subtask_id,
            payload.model_dump(exclude_unset=True),
            day or date.today(),
        )
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=ActivityAction.TODO_SUBTASK_UPDATED,
        user_id=user.id,
        message=f"Subtaak '{subtask.title}' gewijzigd.",
        subject_type="todo_subtask",
        subject_id=subtask.id,
    )
    await session.commit()
    return subtask


@router.delete("/subtasks/{subtask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subtask(
    subtask_id: int,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await todo_service.delete_subtask(session, user.id, subtask_id)
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=ActivityAction.TODO_SUBTASK_DELETED,
        user_id=user.id,
        message="Subtaak verwijderd.",
        subject_type="todo_subtask",
        subject_id=subtask_id,
    )
    await session.commit()


@router.patch("/{task_id}", response_model=TodoTaskOut)
async def update_todo(
    task_id: int,
    payload: TodoTaskPatch,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    # exclude_unset: alleen wat de gebruiker echt meestuurt wordt gewijzigd, zodat een
    # weggelaten veld niet stilletjes op null gaat.
    try:
        task = await todo_service.update_task(
            session, user.id, task_id, payload.model_dump(exclude_unset=True)
        )
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=ActivityAction.TODO_UPDATED,
        user_id=user.id,
        message=f"Taak '{task.title}' gewijzigd.",
        subject_type="todo_task",
        subject_id=task.id,
    )
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    task_id: int,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await todo_service.delete_task(session, user.id, task_id)
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=ActivityAction.TODO_DELETED,
        user_id=user.id,
        message="Taak verwijderd.",
        subject_type="todo_task",
        subject_id=task_id,
    )
    await session.commit()


@router.post("/{task_id}/complete", response_model=CompletionOut)
async def complete_todo(
    task_id: int,
    payload: CompletionIn,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    """Afvinken of terugzetten. Dit is de enige weg; geen enkele integratie mag hier
    langs."""
    day = payload.date or date.today()
    try:
        completion = await todo_service.set_completion(
            session, user.id, task_id, day, payload.completed
        )
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=(
            ActivityAction.TODO_COMPLETED if payload.completed else ActivityAction.TODO_REOPENED
        ),
        user_id=user.id,
        message=f"Taak {task_id} op {day.isoformat()} "
        + ("afgevinkt." if payload.completed else "weer opengezet."),
        subject_type="todo_task",
        subject_id=task_id,
    )
    await session.commit()
    return CompletionOut(
        todo_task_id=completion.todo_task_id,
        date=completion.date,
        completed=completion.completed,
        completed_at=completion.completed_at,
    )


@router.post("/{task_id}/toggle", response_model=CompletionOut)
async def toggle_todo(
    task_id: int,
    day: date | None = Query(default=None),
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    target = day or date.today()
    try:
        completion = await todo_service.toggle(session, user.id, task_id, target)
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=(
            ActivityAction.TODO_COMPLETED
            if completion.completed
            else ActivityAction.TODO_REOPENED
        ),
        user_id=user.id,
        message=f"Taak {task_id} omgezet op {target.isoformat()}.",
        subject_type="todo_task",
        subject_id=task_id,
    )
    await session.commit()
    return CompletionOut(
        todo_task_id=completion.todo_task_id,
        date=completion.date,
        completed=completion.completed,
        completed_at=completion.completed_at,
    )


@router.post(
    "/{task_id}/subtasks", response_model=SubtaskOut, status_code=status.HTTP_201_CREATED
)
async def add_subtask(
    task_id: int,
    payload: SubtaskIn,
    user: User = Depends(write_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        subtask = await todo_service.add_subtask(
            session, user.id, task_id, payload.title, payload.sort_order
        )
    except TodoNotFound:
        raise NOT_FOUND from None
    await log_activity(
        session,
        action=ActivityAction.TODO_SUBTASK_CREATED,
        user_id=user.id,
        message=f"Subtaak '{subtask.title}' toegevoegd.",
        subject_type="todo_subtask",
        subject_id=subtask.id,
    )
    await session.commit()
    return subtask


@router.get("/{task_id}/history", response_model=HistoryOut)
async def todo_history(
    task_id: int,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    try:
        entries = await todo_service.history(
            session, user.id, task_id, today - timedelta(days=days - 1), today
        )
    except TodoNotFound:
        raise NOT_FOUND from None
    return HistoryOut(
        todo_task_id=task_id,
        streak=await todo_service.streak(session, task_id, today),
        days=entries,
    )
