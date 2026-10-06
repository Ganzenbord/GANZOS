"""Quant Lab: de stop per trade in plaats van een vast percentage

Drie kolommen bij `quant_paper_trades`, en één instelling die van naam verandert buiten de
database om (`GANZ_QUANT_PAPER_EQUITY_EUR` wordt `GANZ_QUANT_PAPER_EQUITY_USD`).

Waarom deze kolommen: de stopafstand is niet meer één getal in de hypothese maar volgt per
trade uit wat dat token zelf deed — onder de bodem van het venster waar de koers uit kwam.
Zonder `stop_basis` en `stop_distance_pct` is achteraf niet na te gaan waarom een positie
zo groot was, en dat is precies de vraag die je bij een verlies stelt. `stop_clamped` zegt
of de afgeleide afstand tegen de onder- of bovengrens aanliep.

De tabel kan rijen bevatten, dus de twee NOT NULL-kolommen krijgen een `server_default` die
daarna weer weg gaat. `stop_distance_pct` wordt voor bestaande rijen 0: die trades komen uit
de oude vorm met een vast percentage, en 0 is zichtbaar fout in plaats van stilzwijgend
aannemelijk.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_quant_stop_per_trade"
down_revision = "0008_quant_lab_papieren_handel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quant_paper_trades",
        sa.Column("stop_basis", sa.String(length=300), nullable=False, server_default=""),
    )
    op.add_column(
        "quant_paper_trades",
        sa.Column(
            "stop_distance_pct",
            sa.Numeric(precision=8, scale=4),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "quant_paper_trades",
        sa.Column("stop_clamped", sa.String(length=10), nullable=True),
    )
    op.alter_column("quant_paper_trades", "stop_basis", server_default=None)
    op.alter_column("quant_paper_trades", "stop_distance_pct", server_default=None)


def downgrade() -> None:
    op.drop_column("quant_paper_trades", "stop_clamped")
    op.drop_column("quant_paper_trades", "stop_distance_pct")
    op.drop_column("quant_paper_trades", "stop_basis")
