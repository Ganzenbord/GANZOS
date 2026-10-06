"""Quant Lab: de schaduwlog van de beslismodellen en de inbox van de Reviewer

Twee nieuwe tabellen, geen bestaande kolom aangeraakt.

`quant_decision_log` bewaart elke beslissing van een beslismodel, inclusief die van een
model dat in de schaduw loopt en dus niets bepaalt (`used = false`). Zonder die rijen kun
je de vraag "was het beter geweest" achteraf niet beantwoorden, en dan blijft het bij een
claim van de leverancier. `outcome` mag NULL zijn: een beslissing wordt genomen voordat je
weet hoe het afloopt, en leeg betekent "weten we nog niet" en niet "nee".

`quant_proposals` is de inbox van de Reviewer. Die mag nooit config of een hypothese
wijzigen; zijn voorstellen komen hier terecht en blijven hier tot iemand ze goedkeurt of
afwijst. Een afgewezen voorstel blijft staan — weggooien zou betekenen dat je niet meer
kunt zien wat je hebt afgewezen en waarom, en dat is precies wat je een half jaar later wil
nalezen als iemand hetzelfde voorstelt.

`applied_hypothesis_id` legt vast welke nieuwe hypothese-versie uit een goedgekeurd
voorstel is gekomen. Goedkeuren verandert dus zelf nog niets: het verwijst naar een versie
die apart is geregistreerd met zijn eigen hash.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_quant_agents"
down_revision = "0009_quant_stop_per_trade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quant_decision_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.String(length=64), nullable=False),
        sa.Column("pool_address", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quant_decision_log_created_at"), "quant_decision_log", ["created_at"]
    )
    op.create_index(
        op.f("ix_quant_decision_log_hypothesis"), "quant_decision_log", ["hypothesis"]
    )
    op.create_index(
        "ix_quant_decision_log_model_shadow",
        "quant_decision_log",
        ["model_name", "shadow"],
    )

    op.create_table(
        "quant_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("argument", sa.Text(), nullable=False),
        sa.Column("changes_nl", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_hypothesis_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["applied_hypothesis_id"], ["quant_hypotheses.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_proposals_created_at"), "quant_proposals", ["created_at"])
    op.create_index(op.f("ix_quant_proposals_status"), "quant_proposals", ["status"])


def downgrade() -> None:
    op.drop_table("quant_proposals")
    op.drop_table("quant_decision_log")
