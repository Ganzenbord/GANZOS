from __future__ import annotations

# 'date' is ook een veldnaam hieronder; onder een eigen naam importeren voorkomt
# dat Pydantic de annotatie op het veld zelf laat slaan in plaats van op het type.
from datetime import date as DateOnly
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

from app.models.todo import TodoPriority, TodoRecurrence


class SubtaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sort_order: int | None = None


class SubtaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    completed: bool | None = None


class SubtaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    sort_order: int
    completed: bool


class TodoTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=80)
    priority: TodoPriority = TodoPriority.NORMAL
    recurrence: TodoRecurrence = TodoRecurrence.DAILY
    # "08:00" — alleen een tijdstip, want de dag komt uit de herhaling.
    scheduled_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sort_order: int | None = None
    active: bool = True
    subtasks: list[SubtaskIn] = Field(default_factory=list)


class TodoTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=80)
    priority: TodoPriority | None = None
    recurrence: TodoRecurrence | None = None
    scheduled_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sort_order: int | None = None
    active: bool | None = None


class TodoTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    category: str | None
    priority: str
    recurrence: str
    scheduled_time: str | None
    sort_order: int
    active: bool
    subtasks: list[SubtaskOut] = Field(default_factory=list)


class TodoDayItem(TodoTaskOut):
    completed: bool
    completed_at: UtcDatetime | None = None


class TodoDayOut(BaseModel):
    date: DateOnly
    total: int
    completed: int
    tasks: list[TodoDayItem]


class CompletionIn(BaseModel):
    completed: bool = True
    date: DateOnly | None = None


class CompletionOut(BaseModel):
    todo_task_id: int
    date: DateOnly
    completed: bool
    completed_at: UtcDatetime | None


class ReorderIn(BaseModel):
    order: list[int] = Field(min_length=1)


class HistoryDay(BaseModel):
    date: DateOnly
    status: str
    completed_at: UtcDatetime | None = None


class HistoryOut(BaseModel):
    todo_task_id: int
    streak: int
    days: list[HistoryDay]
