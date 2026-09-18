"""Alle tabellen op één plek, zodat Alembic ze allemaal ziet."""

from app.models.activity import ActivityAction, ActivityLogEntry
from app.models.base import Base, TimestampMixin, UtcDateTime, utcnow
from app.models.confirmation import (
    MAX_ATTEMPTS,
    ConfirmationMethod,
    ConfirmationRequest,
    ConfirmationStatus,
)
from app.models.finance import (
    AccountStatus,
    AccountType,
    FinanceSnapshot,
    FinancialAccount,
)
from app.models.platform import (
    Conversation,
    ConversationMessage,
    Integration,
    IntegrationStatus,
    LlmProviderStatus,
    MemoryEntry,
    MissionStatus,
    MissionTask,
    Skill,
    Workflow,
)
from app.models.social import (
    ChannelStatus,
    SocialChannel,
    SocialChannelStats,
    SocialPlatform,
)
from app.models.todo import (
    TodoCompletion,
    TodoPriority,
    TodoRecurrence,
    TodoSubtask,
    TodoSubtaskCompletion,
    TodoTask,
)
from app.models.upload import (
    OPEN_UPLOAD_STATUSES,
    ContentType,
    UploadRecurrence,
    UploadSchedule,
    UploadStatus,
)
from app.models.user import (
    TIER_GUEST,
    TIER_LIMITED,
    TIER_NONE,
    TIER_OWNER,
    TIER_TRUSTED,
    TIERS,
    User,
)
from app.models.video import Video, VideoStatus
from app.models.voice import VoiceProfile

__all__ = [
    "AccountStatus",
    "AccountType",
    "ActivityAction",
    "ActivityLogEntry",
    "Base",
    "ChannelStatus",
    "ConfirmationMethod",
    "ConfirmationRequest",
    "ConfirmationStatus",
    "ContentType",
    "Conversation",
    "ConversationMessage",
    "FinanceSnapshot",
    "FinancialAccount",
    "Integration",
    "IntegrationStatus",
    "LlmProviderStatus",
    "MAX_ATTEMPTS",
    "MemoryEntry",
    "MissionStatus",
    "MissionTask",
    "OPEN_UPLOAD_STATUSES",
    "Skill",
    "SocialChannel",
    "SocialChannelStats",
    "SocialPlatform",
    "TIERS",
    "TIER_GUEST",
    "TIER_LIMITED",
    "TIER_OWNER",
    "TIER_NONE",
    "TIER_TRUSTED",
    "TimestampMixin",
    "UtcDateTime",
    "TodoCompletion",
    "TodoPriority",
    "TodoRecurrence",
    "TodoSubtask",
    "TodoSubtaskCompletion",
    "TodoTask",
    "UploadRecurrence",
    "UploadSchedule",
    "UploadStatus",
    "User",
    "Video",
    "VideoStatus",
    "VoiceProfile",
    "Workflow",
    "utcnow",
]
