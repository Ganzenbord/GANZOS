"""Quant Lab: de datalaag en de replay

Drie nieuwe tabellen, geen enkele bestaande kolom aangeraakt.

`quant_raw_events` is de feed zoals hij binnenkwam: de tekst, niet een geparste structuur.
Daar zit het verschil tussen "herhaalbaar" en "bit-voor-bit herhaalbaar" — twee JSON-
documenten met dezelfde betekenis kunnen andere bytes zijn, en een feed die morgen zijn
sleutelvolgorde wijzigt zou anders stil een ander corpus opleveren. `chain_hash` hangt elke
rij aan de vorige, zodat een wijziging in een oude rij zichtbaar is.

`quant_market_ticks` is het genormaliseerde deel en hangt met ON DELETE CASCADE aan de ruwe
rijen. Volledig afgeleid en dus volledig weggooibaar: dat is wat het mogelijk maakt om te
bewijzen dat een replay hetzelfde resultaat geeft.

`quant_ingest_runs` houdt bij wat de Scout wanneer heeft opgenomen, inclusief waarom hij
stopte. Een run die stilletjes ophoudt, laat een gat in het corpus achter dat je nooit meer
kunt vullen.

Allemaal nieuw en leeg, dus er valt niets te vullen.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_quant_lab_datalaag"
down_revision = "0006_quant_lab_risk_en_kosten"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quant_raw_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("stream", sa.String(length=40), nullable=False),
        sa.Column("payload_raw", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("chain_hash", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("ingest_run_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        op.f("ix_quant_raw_events_ingest_run_id"), "quant_raw_events", ["ingest_run_id"]
    )
    op.create_index(
        op.f("ix_quant_raw_events_received_at"), "quant_raw_events", ["received_at"]
    )
    op.create_index(
        "ix_quant_raw_events_source_received", "quant_raw_events", ["source", "received_at"]
    )
    op.create_index(
        "ix_quant_raw_events_stream_hash",
        "quant_raw_events",
        ["source", "stream", "payload_hash"],
    )

    op.create_table(
        "quant_market_ticks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_event_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=40), nullable=False),
        sa.Column("chain", sa.String(length=40), nullable=False),
        sa.Column("pool_address", sa.String(length=80), nullable=False),
        sa.Column("token_address", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_usd", sa.Numeric(precision=30, scale=12), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("volume_usd", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("volume_window_seconds", sa.Integer(), nullable=True),
        sa.Column("pool_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["raw_event_id"], ["quant_raw_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quant_market_ticks_observed_at"), "quant_market_ticks", ["observed_at"]
    )
    op.create_index(
        op.f("ix_quant_market_ticks_raw_event_id"), "quant_market_ticks", ["raw_event_id"]
    )
    op.create_index(
        "ix_quant_market_ticks_pool_observed",
        "quant_market_ticks",
        ["pool_address", "observed_at"],
    )

    op.create_table(
        "quant_ingest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(length=40), nullable=True),
        sa.Column("events", sa.Integer(), nullable=False),
        sa.Column("ticks", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("parse_failures", sa.Integer(), nullable=False),
        sa.Column("bytes_stored", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_ingest_runs_source"), "quant_ingest_runs", ["source"])
    op.create_index(
        op.f("ix_quant_ingest_runs_started_at"), "quant_ingest_runs", ["started_at"]
    )


def downgrade() -> None:
    op.drop_table("quant_ingest_runs")
    op.drop_table("quant_market_ticks")
    op.drop_table("quant_raw_events")
