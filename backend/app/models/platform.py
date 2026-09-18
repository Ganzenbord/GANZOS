"""De bestaande Ganz-modules: skills, taken, geheugen, gesprekken, integraties,
workflows en de status van de taalmodellen.

Deze staan bij elkaar omdat ze samen "Ganz zelf" vormen; de vier dashboardmodules
(todo, finance, social, uploads) hebben hun eigen bestand.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime, utcnow


class Skill(Base, TimestampMixin):
    """Iets dat Ganz kan, vastgelegd zodat het herhaald kan worden.

    Een skill is een naam, een omschrijving waarop gematcht wordt, en een rijtje stappen.
    De stappen staan als JSON omdat hun vorm nog beweegt; wat vastligt (wie het mag, hoe
    vaak het lukte) staat in gewone kolommen.
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # Waar deze skill op aanslaat. Losse woorden of korte zinnen, met | ertussen:
    # "video uploaden|zet de video online". Leeg betekent: alleen op naam en omschrijving.
    trigger_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)

    # De stappen, bijvoorbeeld [{"tool": "youtube.upload", "action": "upload"}].
    # Wat een stap precies mag, staat in app/services/skill_executor.py.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # Het recht dat nodig is om deze skill te draaien. Leeg = geen extra eis bovenop
    # `tasks.execute`. Staat als sleutel in het register, niet als los if-je hier.
    required_permission: Mapped[str | None] = mapped_column(String(80), nullable=True)

    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Gaat omhoog bij elke wijziging van de stappen, zodat je in het logboek kunt zien
    # wélke versie er draaide toen iets misging.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MissionStatus(StrEnum):
    """De toestanden die een taak kan hebben.

    De namen komen uit de bestaande Command Center-tijdlijn en staan al in de frontend.
    Ze dekken wat de architectuurprompt vraagt; alleen de woorden verschillen:

    | prompt               | hier      |
    | -------------------- | --------- |
    | pending              | planned   |
    | matching             | matching  |
    | executing            | running   |
    | completed            | done      |
    | waiting_confirmation | waiting   |
    | failed               | failed    |
    | cancelled            | cancelled |
    """

    PLANNED = "planned"
    MATCHING = "matching"
    RUNNING = "running"
    DONE = "done"
    WAITING = "waiting"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Een taak die hierin staat is klaar: er gebeurt niets meer mee.
FINAL_STATUSES = frozenset({MissionStatus.DONE, MissionStatus.FAILED, MissionStatus.CANCELLED})


class MissionTask(Base, TimestampMixin):
    """De Mission/Tasks-tijdlijn: wat Ganz zelf uitvoert.

    Bewust gescheiden van TodoTask. Een missie mag Ganz zelf afronden; een to-do
    vinkt alleen de gebruiker af.
    """

    __tablename__ = "mission_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=MissionStatus.PLANNED, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        UtcDateTime, index=True, nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Welke skill hem uitvoerde. Verdwijnt de skill, dan blijft de taak staan: wat gedaan is,
    # is gedaan.
    skill_id: Mapped[int | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Waarom die skill gekozen is, of waarom geen enkele. Altijd invullen: zonder uitleg is
    # een verkeerde match niet na te trekken.
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(48), default="note", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Gesprek")
    last_message_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="noload"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class IntegrationStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REAUTH_REQUIRED = "reauth_required"
    ERROR = "error"


class Integration(Base, TimestampMixin):
    """Een gekoppelde dienst. Tokens staan hier versleuteld, nooit in platte tekst."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=IntegrationStatus.DISCONNECTED, nullable=False
    )
    status_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    steps: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class LlmProviderStatus(Base):
    """De laatst gemeten toestand van een taalmodel. Wordt door de scheduler gevuld."""

    __tablename__ = "llm_provider_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
