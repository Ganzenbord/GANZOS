"""De dagelijkse to-do lijst.

Belangrijk uitgangspunt: een taak wordt nooit automatisch afgevinkt omdat een
integratie iets heeft gedaan. Alleen de gebruiker bevestigt. Daarom staat de stand
per dag in een eigen rij (TodoCompletion), en niet als vlaggetje op de taak zelf:
zo blijft 15 september afgevinkt terwijl 16 september nog open staat.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TodoPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TodoRecurrence(StrEnum):
    """Hoe vaak een taak terugkomt. ONCE verdwijnt zodra hij af is."""

    ONCE = "once"
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    WEEKLY = "weekly"


class TodoTask(Base, TimestampMixin):
    __tablename__ = "todo_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default=TodoPriority.NORMAL, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recurrence: Mapped[str] = mapped_column(String(16), default=TodoRecurrence.DAILY, nullable=False)
    # Alleen een tijdstip, geen datum: "elke dag om 08:00".
    scheduled_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    subtasks: Mapped[list["TodoSubtask"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TodoSubtask.sort_order",
        lazy="selectin",
    )
    completions: Mapped[list["TodoCompletion"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="noload"
    )


class TodoSubtask(Base):
    __tablename__ = "todo_subtasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    todo_task_id: Mapped[int] = mapped_column(
        ForeignKey("todo_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # De stand van vandaag, als snelle kopie. De waarheid per dag staat in
    # TodoSubtaskCompletion; lees daar altijd uit als je een datum nodig hebt.
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    task: Mapped[TodoTask] = relationship(back_populates="subtasks")


class TodoCompletion(Base):
    __tablename__ = "todo_completions"
    __table_args__ = (UniqueConstraint("todo_task_id", "date", name="uq_todo_completion_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    todo_task_id: Mapped[int] = mapped_column(
        ForeignKey("todo_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[TodoTask] = relationship(back_populates="completions")


class TodoSubtaskCompletion(Base):
    """Per dag per subtaak. Zonder deze tabel zou "Pip gevoerd" morgen nog aan staan."""

    __tablename__ = "todo_subtask_completions"
    __table_args__ = (
        UniqueConstraint("todo_subtask_id", "date", name="uq_todo_subtask_completion_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    todo_subtask_id: Mapped[int] = mapped_column(
        ForeignKey("todo_subtasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
