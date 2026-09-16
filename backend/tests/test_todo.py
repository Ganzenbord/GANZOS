"""Tests voor de dagelijkse takenlijst."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.todo import TodoRecurrence
from app.services import todo_service
from tests.conftest import auth_headers

MONDAY = date(2025, 9, 15)
TUESDAY = date(2025, 9, 16)
WEDNESDAY = date(2025, 9, 17)
SATURDAY = date(2025, 9, 20)


async def _task(session, user, **kwargs):
    data = {
        "title": "Katten eten geven",
        "recurrence": TodoRecurrence.DAILY,
        "subtasks": [{"title": "Pip"}, {"title": "Johann"}],
        **kwargs,
    }
    task = await todo_service.create_task(session, user.id, data)
    await session.commit()
    return task


async def test_daily_todo_retrieval(session, owner):
    await _task(session, owner)
    day = await todo_service.get_day(session, owner.id, MONDAY)
    assert day["total"] == 1
    assert day["completed"] == 0
    assert [sub["title"] for sub in day["tasks"][0]["subtasks"]] == ["Pip", "Johann"]


async def test_completion_is_per_day(session, owner):
    """Het voorbeeld uit de opdracht: 15 september af, 16 september nog niet."""
    task = await _task(session, owner)
    await todo_service.set_completion(session, owner.id, task.id, MONDAY, True)
    await session.commit()

    monday = await todo_service.get_day(session, owner.id, MONDAY)
    tuesday = await todo_service.get_day(session, owner.id, TUESDAY)
    assert monday["tasks"][0]["completed"] is True
    assert monday["completed"] == 1
    assert tuesday["tasks"][0]["completed"] is False
    assert tuesday["completed"] == 0


async def test_history_distinguishes_not_started_from_not_completed(session, owner):
    task = await _task(session, owner)
    await todo_service.set_completion(session, owner.id, task.id, MONDAY, True)
    await todo_service.set_completion(session, owner.id, task.id, TUESDAY, False)
    await session.commit()

    days = await todo_service.history(session, owner.id, task.id, MONDAY, WEDNESDAY)
    assert [row["status"] for row in days] == ["completed", "not_completed", "not_started"]


async def test_subtask_completion_resets_the_next_day(session, owner):
    task = await _task(session, owner)
    pip = task.subtasks[0]
    await todo_service.set_subtask_completion(session, owner.id, pip.id, MONDAY, True)
    await session.commit()

    monday = await todo_service.get_day(session, owner.id, MONDAY)
    tuesday = await todo_service.get_day(session, owner.id, TUESDAY)
    assert monday["tasks"][0]["subtasks"][0]["completed"] is True
    assert tuesday["tasks"][0]["subtasks"][0]["completed"] is False


async def test_recurrence_weekdays_and_weekends(session, owner):
    await _task(session, owner, title="Werkdag", recurrence=TodoRecurrence.WEEKDAYS)
    await _task(session, owner, title="Weekend", recurrence=TodoRecurrence.WEEKENDS)

    monday = await todo_service.get_day(session, owner.id, MONDAY)
    saturday = await todo_service.get_day(session, owner.id, SATURDAY)
    assert [t["title"] for t in monday["tasks"]] == ["Werkdag"]
    assert [t["title"] for t in saturday["tasks"]] == ["Weekend"]


async def test_once_disappears_after_completion(session, owner):
    task = await _task(session, owner, title="Eenmalig", recurrence=TodoRecurrence.ONCE)
    assert (await todo_service.get_day(session, owner.id, MONDAY))["total"] == 1

    await todo_service.set_completion(session, owner.id, task.id, MONDAY, True)
    await session.commit()

    # Op de dag zelf blijft hij afgevinkt staan, daarna is hij weg.
    assert (await todo_service.get_day(session, owner.id, MONDAY))["total"] == 1
    assert (await todo_service.get_day(session, owner.id, TUESDAY))["total"] == 0


async def test_weekly_disappears_for_the_rest_of_the_week(session, owner):
    task = await _task(session, owner, title="Wekelijks", recurrence=TodoRecurrence.WEEKLY)
    await todo_service.set_completion(session, owner.id, task.id, MONDAY, True)
    await session.commit()

    assert (await todo_service.get_day(session, owner.id, TUESDAY))["total"] == 0
    # Maandag daarop is een nieuwe week.
    assert (await todo_service.get_day(session, owner.id, MONDAY + timedelta(days=7)))[
        "total"
    ] == 1


async def test_streak_counts_consecutive_days(session, owner):
    task = await _task(session, owner)
    for day in (MONDAY, TUESDAY, WEDNESDAY):
        await todo_service.set_completion(session, owner.id, task.id, day, True)
    await session.commit()
    assert await todo_service.streak(session, task.id, WEDNESDAY) == 3


async def test_another_user_cannot_touch_the_task(session, owner, trusted):
    task = await _task(session, owner)
    with pytest.raises(todo_service.TodoNotFound):
        await todo_service.set_completion(session, trusted.id, task.id, MONDAY, True)


async def test_api_create_toggle_and_log(client, owner, session):
    response = await client.post(
        "/todos",
        json={"title": "Back-up controleren", "recurrence": "daily", "scheduled_time": "09:00"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201
    task_id = response.json()["id"]

    toggled = await client.post(f"/todos/{task_id}/toggle", headers=auth_headers(owner))
    assert toggled.status_code == 200
    assert toggled.json()["completed"] is True

    activity = await client.get("/activity", headers=auth_headers(owner))
    actions = [row["action"] for row in activity.json()]
    assert "TODO_CREATED" in actions
    assert "TODO_COMPLETED" in actions


async def test_api_requires_write_permission(client, limited, owner, session):
    await _task(session, owner)
    # Tier 3 mag kijken...
    assert (await client.get("/todos/today", headers=auth_headers(limited))).status_code == 200
    # ...maar niet schrijven.
    blocked = await client.post(
        "/todos", json={"title": "Mag niet"}, headers=auth_headers(limited)
    )
    assert blocked.status_code == 403


async def test_subtask_route_is_not_swallowed_by_task_route(client, owner, session):
    task = await _task(session, owner)
    response = await client.patch(
        f"/todos/subtasks/{task.subtasks[0].id}",
        json={"completed": True},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["completed"] is True
