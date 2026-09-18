"""Wat /api/skills en /api/tasks aannemen en teruggeven."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StepIn(BaseModel):
    tool: str = Field(description="De naam van het gereedschap, bijvoorbeeld 'youtube.upload'")
    action: str | None = None

    model_config = {"extra": "allow"}


class SkillOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    category: str | None = None
    enabled: bool
    trigger_pattern: str | None = None
    steps: list[dict[str, Any]]
    required_permission: str | None = None
    run_count: int
    success_count: int
    failure_count: int
    version: int
    last_used_at: datetime | None = None


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    category: str | None = None
    trigger_pattern: str | None = Field(
        default=None,
        description="Woorden of zinnen waarop deze skill aanslaat, met | ertussen",
    )
    steps: list[dict[str, Any]] = Field(
        default_factory=list, description="De stappen, elk met minstens een 'tool'"
    )
    required_permission: str | None = None
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    category: str | None = None
    trigger_pattern: str | None = None
    steps: list[dict[str, Any]] | None = None
    required_permission: str | None = None
    enabled: bool | None = None


class ToolOut(BaseModel):
    name: str
    description: str
    sensitive: bool
    simulated: bool


class TaskOut(BaseModel):
    id: int
    title: str
    description: str | None = None
    status: str
    skill_id: int | None = None
    match_confidence: float | None = None
    match_reason: str | None = Field(
        default=None, description="Waarom deze skill gekozen is, of waarom geen enkele"
    )
    result: dict[str, Any]
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class MatchOut(BaseModel):
    matched: bool
    confidence: float
    threshold: float
    reason: str
    backend: str = Field(description="Waarop gematcht is: 'woorden' of 'betekenis'")
    skill: SkillOut | None = None
    task: TaskOut


class ExecuteOut(BaseModel):
    ok: bool
    task: TaskOut
    steps: list[dict[str, Any]]
    error: str | None = None
    simulated: bool = Field(
        default=True,
        description="Zolang dit true is heeft Ganz de stappen nagelopen maar niets in de "
        "buitenwereld gedaan.",
    )
