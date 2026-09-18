"""Skill-engine en takenloop (fase 3)

`skills` krijgt erbij wat een skill uitvoerbaar maakt: waar hij op aanslaat
(`trigger_pattern`), wat hij doet (`steps`, JSON), welk recht daarvoor nodig is, en hoe vaak
het lukte of misging. `version` loopt op zodra de stappen veranderen, zodat in het logboek
te zien is wélke versie draaide toen iets misging.

`mission_tasks` krijgt de loop erbij: welke skill gekozen is, hoe zeker dat was en waarom
(`match_reason` — ook als er níéts paste), wanneer hij begon, en wat eruit kwam.

De bestaande statuswoorden blijven zoals ze zijn, want de frontend kent ze al. Er komen er
twee bij: `matching` en `cancelled`. De vertaling naar de namen uit de architectuurprompt
staat in app/models/platform.py bij MissionStatus.

Revision ID: 0004_skill_engine_and_tasks
Revises: 0003_voice_pin_and_confirmations
Create Date: 2026-09-18 09:50:40.874028
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0004_skill_engine_and_tasks'
down_revision = '0003_voice_pin_and_confirmations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # De nieuwe NOT NULL-kolommen krijgen een server_default mee. Zonder dat mislukt deze
    # migratie op elke database waar al skills of taken in staan: PostgreSQL weet dan niet
    # wat het in de bestaande rijen moet zetten. Na het vullen gaat de default er weer af,
    # want de waarde hoort uit het model te komen, niet uit de database.
    op.add_column(
        "mission_tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("mission_tasks", sa.Column("skill_id", sa.Integer(), nullable=True))
    op.add_column("mission_tasks", sa.Column("match_confidence", sa.Float(), nullable=True))
    op.add_column("mission_tasks", sa.Column("match_reason", sa.Text(), nullable=True))
    op.add_column(
        "mission_tasks",
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("mission_tasks", sa.Column("error", sa.Text(), nullable=True))
    op.alter_column("mission_tasks", "result", server_default=None)

    op.create_index(
        op.f("ix_mission_tasks_skill_id"), "mission_tasks", ["skill_id"], unique=False
    )
    # Met een naam, zodat hij later weer te verwijderen is.
    op.create_foreign_key(
        "fk_mission_tasks_skill_id_skills",
        "mission_tasks",
        "skills",
        ["skill_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("skills", sa.Column("trigger_pattern", sa.Text(), nullable=True))
    op.add_column(
        "skills", sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
    )
    op.add_column(
        "skills", sa.Column("required_permission", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "skills", sa.Column("success_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "skills", sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "skills", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    for kolom in ("steps", "success_count", "failure_count", "version"):
        op.alter_column("skills", kolom, server_default=None)


def downgrade() -> None:
    op.drop_column("skills", "version")
    op.drop_column("skills", "failure_count")
    op.drop_column("skills", "success_count")
    op.drop_column("skills", "required_permission")
    op.drop_column("skills", "steps")
    op.drop_column("skills", "trigger_pattern")

    op.drop_constraint("fk_mission_tasks_skill_id_skills", "mission_tasks", type_="foreignkey")
    op.drop_index(op.f("ix_mission_tasks_skill_id"), table_name="mission_tasks")
    op.drop_column("mission_tasks", "error")
    op.drop_column("mission_tasks", "result")
    op.drop_column("mission_tasks", "match_reason")
    op.drop_column("mission_tasks", "match_confidence")
    op.drop_column("mission_tasks", "skill_id")
    op.drop_column("mission_tasks", "started_at")
