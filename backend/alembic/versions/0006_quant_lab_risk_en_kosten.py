"""Quant Lab: de risicolaag en het kostenboek

Vijf nieuwe tabellen, geen enkele bestaande kolom aangeraakt. Allemaal nieuw en leeg, dus
er valt niets te vullen en `server_default` is alleen nodig waar de kolom een tijdstip is.

Waarom geen `user_id` op vier van de vijf: dit is één lab en niet een lab per gebruiker.
De equity, de risicogrenzen en het budget zijn van het lab als geheel; wie er naar mag
kijken regelt het rechtenregister. Bij `quant_risk_controls` staat wél een gebruiker,
want daar gaat het erom wie op de noodstop heeft gedrukt — en die blijft bewaard als het
account later verdwijnt (`SET NULL`), zodat het logboek geen gat krijgt.

Er wordt in dit lab niet live gehandeld. Elke rij hier gaat over papier.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_quant_lab_risk_en_kosten"
down_revision = "0005_sessions_and_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quant_risk_bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.String(length=64), nullable=False),
        sa.Column("r_multiple", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quant_risk_bookings_closed_at"), "quant_risk_bookings", ["closed_at"]
    )
    op.create_index(
        op.f("ix_quant_risk_bookings_hypothesis"), "quant_risk_bookings", ["hypothesis"]
    )

    op.create_table(
        "quant_risk_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.String(length=64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("veto", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("equity", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("risk_eur", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("position_units", sa.Numeric(precision=30, scale=8), nullable=False),
        sa.Column("open_risk_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("realized_day_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("realized_week_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_risk_events_created_at"), "quant_risk_events", ["created_at"])
    op.create_index(op.f("ix_quant_risk_events_hypothesis"), "quant_risk_events", ["hypothesis"])
    op.create_index(op.f("ix_quant_risk_events_veto"), "quant_risk_events", ["veto"])

    op.create_table(
        "quant_risk_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("control", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_risk_controls_control"), "quant_risk_controls", ["control"])
    op.create_index(
        op.f("ix_quant_risk_controls_created_at"), "quant_risk_controls", ["created_at"]
    )
    op.create_index(op.f("ix_quant_risk_controls_user_id"), "quant_risk_controls", ["user_id"])

    op.create_table(
        "quant_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("component"),
    )

    op.create_table(
        "quant_llm_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("cost_eur", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_llm_calls_agent"), "quant_llm_calls", ["agent"])
    op.create_index(op.f("ix_quant_llm_calls_created_at"), "quant_llm_calls", ["created_at"])
    op.create_index(op.f("ix_quant_llm_calls_model"), "quant_llm_calls", ["model"])


def downgrade() -> None:
    op.drop_table("quant_llm_calls")
    op.drop_table("quant_heartbeats")
    op.drop_table("quant_risk_controls")
    op.drop_table("quant_risk_events")
    op.drop_table("quant_risk_bookings")
