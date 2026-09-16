"""De dagelijkse takenlijst.

Twee regels bepalen bijna alles hier:

1. Alleen de gebruiker vinkt af. Er is geen enkele weg waarlangs een integratie een
   taak op voltooid zet.
2. De stand hoort bij een dag, niet bij de taak. Daarom wordt er per dag een
   completion-rij gemaakt en blijft de geschiedenis staan.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.todo import (
    TodoCompletion,
    TodoRecurrence,
    TodoSubtask,
    TodoSubtaskCompletion,
    TodoTask,
)
from app.utils.timeutil import todo_occurs_on


class TodoNotFound(Exception):
    """De taak bestaat niet, of is niet van deze gebruiker."""


def _iso_week(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso[0], iso[1]


async def _owned_task(session: AsyncSession, task_id: int, user_id: int) -> TodoTask:
    task = await session.get(TodoTask, task_id)
    if task is None or task.user_id != user_id:
        # Bewust dezelfde fout voor "bestaat niet" en "niet van jou": anders kun je
        # via de foutmelding afleiden welke taak-ID's bestaan.
        raise TodoNotFound
    return task


async def _completed_dates(session: AsyncSession, task_ids: Sequence[int]) -> dict[int, set[date]]:
    """Op welke dagen een taak is afgevinkt. Nodig om eenmalige en wekelijkse taken
    van de lijst te halen zodra ze klaar zijn."""
    if not task_ids:
        return {}
    result = await session.execute(
        select(TodoCompletion.todo_task_id, TodoCompletion.date).where(
            TodoCompletion.todo_task_id.in_(task_ids), TodoCompletion.completed.is_(True)
        )
    )
    done: dict[int, set[date]] = {}
    for task_id, day in result.all():
        done.setdefault(task_id, set()).add(day)
    return done


def _is_visible(task: TodoTask, day: date, completed_on: set[date]) -> bool:
    if not todo_occurs_on(task.recurrence, day):
        return False
    if task.recurrence == TodoRecurrence.ONCE:
        # Klaar is klaar: alleen nog zichtbaar op de dag dat het gebeurde.
        return not any(done != day for done in completed_on)
    if task.recurrence == TodoRecurrence.WEEKLY:
        week = _iso_week(day)
        return not any(done != day and _iso_week(done) == week for done in completed_on)
    return True


async def get_day(session: AsyncSession, user_id: int, day: date) -> dict[str, Any]:
    """Alles wat het dashboard en het volledige todo-scherm nodig hebben voor één dag."""
    result = await session.execute(
        select(TodoTask)
        .where(TodoTask.user_id == user_id, TodoTask.active.is_(True))
        .order_by(TodoTask.sort_order, TodoTask.scheduled_time, TodoTask.id)
    )
    tasks = list(result.scalars().all())
    task_ids = [task.id for task in tasks]

    completed_on = await _completed_dates(session, task_ids)
    visible = [task for task in tasks if _is_visible(task, day, completed_on.get(task.id, set()))]
    visible_ids = [task.id for task in visible]

    day_completions = {}
    if visible_ids:
        rows = await session.execute(
            select(TodoCompletion).where(
                TodoCompletion.todo_task_id.in_(visible_ids), TodoCompletion.date == day
            )
        )
        day_completions = {row.todo_task_id: row for row in rows.scalars().all()}

    subtask_ids = [sub.id for task in visible for sub in task.subtasks]
    sub_completions: dict[int, TodoSubtaskCompletion] = {}
    if subtask_ids:
        rows = await session.execute(
            select(TodoSubtaskCompletion).where(
                TodoSubtaskCompletion.todo_subtask_id.in_(subtask_ids),
                TodoSubtaskCompletion.date == day,
            )
        )
        sub_completions = {row.todo_subtask_id: row for row in rows.scalars().all()}

    items = []
    for task in visible:
        completion = day_completions.get(task.id)
        items.append(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "category": task.category,
                "priority": task.priority,
                "recurrence": task.recurrence,
                "scheduled_time": task.scheduled_time,
                "sort_order": task.sort_order,
                "active": task.active,
                "completed": bool(completion and completion.completed),
                "completed_at": completion.completed_at if completion else None,
                "subtasks": [
                    {
                        "id": sub.id,
                        "title": sub.title,
                        "sort_order": sub.sort_order,
                        "completed": bool(
                            sub_completions.get(sub.id)
                            and sub_completions[sub.id].completed
                        ),
                    }
                    for sub in task.subtasks
                ],
            }
        )

    return {
        "date": day,
        "total": len(items),
        "completed": sum(1 for item in items if item["completed"]),
        "tasks": items,
    }


async def list_tasks(session: AsyncSession, user_id: int) -> Sequence[TodoTask]:
    result = await session.execute(
        select(TodoTask)
        .where(TodoTask.user_id == user_id)
        .order_by(TodoTask.sort_order, TodoTask.id)
    )
    return result.scalars().all()


async def create_task(session: AsyncSession, user_id: int, data: dict[str, Any]) -> TodoTask:
    subtasks: Iterable[dict[str, Any]] = data.pop("subtasks", []) or []
    if data.get("sort_order") is None:
        highest = await session.scalar(
            select(func.max(TodoTask.sort_order)).where(TodoTask.user_id == user_id)
        )
        data["sort_order"] = (highest or 0) + 1
    task = TodoTask(user_id=user_id, **data)
    for index, sub in enumerate(subtasks):
        task.subtasks.append(
            TodoSubtask(title=sub["title"], sort_order=sub.get("sort_order") or index)
        )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def update_task(
    session: AsyncSession, user_id: int, task_id: int, data: dict[str, Any]
) -> TodoTask:
    task = await _owned_task(session, task_id, user_id)
    for field, value in data.items():
        setattr(task, field, value)
    await session.flush()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, user_id: int, task_id: int) -> None:
    task = await _owned_task(session, task_id, user_id)
    await session.delete(task)
    await session.flush()


async def set_completion(
    session: AsyncSession, user_id: int, task_id: int, day: date, completed: bool
) -> TodoCompletion:
    """Zet de stand van één dag. Dit is de enige weg waarlangs een taak afgaat."""
    task = await _owned_task(session, task_id, user_id)
    completion = await session.scalar(
        select(TodoCompletion).where(
            TodoCompletion.todo_task_id == task.id, TodoCompletion.date == day
        )
    )
    if completion is None:
        completion = TodoCompletion(todo_task_id=task.id, user_id=user_id, date=day)
        session.add(completion)
    completion.completed = completed
    completion.completed_at = utcnow() if completed else None
    await session.flush()
    return completion


async def toggle(
    session: AsyncSession, user_id: int, task_id: int, day: date
) -> TodoCompletion:
    current = await session.scalar(
        select(TodoCompletion).where(
            TodoCompletion.todo_task_id == task_id, TodoCompletion.date == day
        )
    )
    return await set_completion(
        session, user_id, task_id, day, not (current.completed if current else False)
    )


async def add_subtask(
    session: AsyncSession, user_id: int, task_id: int, title: str, sort_order: int | None = None
) -> TodoSubtask:
    task = await _owned_task(session, task_id, user_id)
    if sort_order is None:
        sort_order = len(task.subtasks)
    subtask = TodoSubtask(todo_task_id=task.id, title=title, sort_order=sort_order)
    session.add(subtask)
    await session.flush()
    return subtask


async def _owned_subtask(session: AsyncSession, subtask_id: int, user_id: int) -> TodoSubtask:
    subtask = await session.get(TodoSubtask, subtask_id)
    if subtask is None:
        raise TodoNotFound
    await _owned_task(session, subtask.todo_task_id, user_id)
    return subtask


async def update_subtask(
    session: AsyncSession, user_id: int, subtask_id: int, data: dict[str, Any], day: date
) -> TodoSubtask:
    subtask = await _owned_subtask(session, subtask_id, user_id)
    if "completed" in data:
        await set_subtask_completion(session, user_id, subtask_id, day, bool(data.pop("completed")))
    for field, value in data.items():
        setattr(subtask, field, value)
    await session.flush()
    return subtask


async def set_subtask_completion(
    session: AsyncSession, user_id: int, subtask_id: int, day: date, completed: bool
) -> TodoSubtaskCompletion:
    subtask = await _owned_subtask(session, subtask_id, user_id)
    row = await session.scalar(
        select(TodoSubtaskCompletion).where(
            TodoSubtaskCompletion.todo_subtask_id == subtask.id,
            TodoSubtaskCompletion.date == day,
        )
    )
    if row is None:
        row = TodoSubtaskCompletion(todo_subtask_id=subtask.id, date=day)
        session.add(row)
    row.completed = completed
    row.completed_at = utcnow() if completed else None
    # Kopie op de subtaak zelf, zodat een los opgehaalde subtaak niet misleidt.
    subtask.completed = completed
    await session.flush()
    return row


async def delete_subtask(session: AsyncSession, user_id: int, subtask_id: int) -> None:
    subtask = await _owned_subtask(session, subtask_id, user_id)
    await session.execute(
        delete(TodoSubtaskCompletion).where(TodoSubtaskCompletion.todo_subtask_id == subtask.id)
    )
    await session.delete(subtask)
    await session.flush()


async def reorder(session: AsyncSession, user_id: int, order: Sequence[int]) -> None:
    """Zet de volgorde in één keer, zoals de gebruiker hem heeft gesleept."""
    for position, task_id in enumerate(order):
        task = await _owned_task(session, task_id, user_id)
        task.sort_order = position
    await session.flush()


async def history(
    session: AsyncSession, user_id: int, task_id: int, start: date, end: date
) -> list[dict[str, Any]]:
    """De stand per dag tussen twee datums.

    Een dag zonder rij is "nog niet begonnen" en dus iets anders dan "niet voltooid";
    dat verschil blijft hier zichtbaar.
    """
    task = await _owned_task(session, task_id, user_id)
    rows = await session.execute(
        select(TodoCompletion).where(
            TodoCompletion.todo_task_id == task.id,
            TodoCompletion.date >= start,
            TodoCompletion.date <= end,
        )
    )
    by_date = {row.date: row for row in rows.scalars().all()}

    days: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        if todo_occurs_on(task.recurrence, cursor):
            row = by_date.get(cursor)
            days.append(
                {
                    "date": cursor,
                    "status": (
                        "completed"
                        if row and row.completed
                        else "not_completed"
                        if row
                        else "not_started"
                    ),
                    "completed_at": row.completed_at if row else None,
                }
            )
        cursor += timedelta(days=1)
    return days


async def streak(session: AsyncSession, task_id: int, today: date) -> int:
    """Hoeveel dagen op rij afgevinkt, tot en met vandaag."""
    rows = await session.execute(
        select(TodoCompletion.date)
        .where(TodoCompletion.todo_task_id == task_id, TodoCompletion.completed.is_(True))
        .order_by(TodoCompletion.date.desc())
    )
    done = {row for row in rows.scalars().all()}
    count = 0
    cursor = today
    while cursor in done:
        count += 1
        cursor -= timedelta(days=1)
    return count


def parse_day(value: str | date | None, fallback: datetime | None = None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(value)
    return (fallback or utcnow()).date()
