"""Quant Lab: de papieren handel en de pre-registratie

Vijf nieuwe tabellen, geen bestaande kolom aangeraakt.

`quant_hypotheses` is de pre-registratie: naam, versie, de hash en de **hele brontekst**.
De tekst staat erin en niet alleen de hash, omdat een hash alleen zegt dát er iets is
veranderd. Met de tekst kun je over een half jaar nalezen waarom een waarde zo stond — en
het commentaar in dat bestand telt mee in de hash, want dat is onderdeel van de registratie.
`(name, version)` is uniek: wijzigen betekent een nieuwe versie, en dan begint de
trade-teller opnieuw.

`quant_signals` bewaart ook de signalen die níét zijn genomen, met de reden. Zonder die
rijen kun je achteraf elke uitkomst mooi praten door te vergeten wat je hebt laten lopen,
en kun je niet meten of een filter geld bespaarde of kansen kostte.

`quant_paper_fills` bewaart vier prijzen per order: verwacht, markt na de vertraging, de
fill, en de kosten apart. "De fill was slechter" zegt niets als je niet weet of dat door de
klok, de pooldiepte of de fee kwam.

Er wordt in dit project niet live gehandeld. Elke rij hier is een simulatie.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_quant_lab_papieren_handel"
down_revision = "0007_quant_lab_datalaag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quant_hypotheses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("paper_only", sa.Boolean(), nullable=False),
        sa.Column("source_yaml", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=300), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_quant_hypothesis_version"),
    )

    op.create_table(
        "quant_strategy_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("corpus_digest", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ticks", sa.Integer(), nullable=False),
        sa.Column("signals_proposed", sa.Integer(), nullable=False),
        sa.Column("trades_opened", sa.Integer(), nullable=False),
        sa.Column("trades_closed", sa.Integer(), nullable=False),
        sa.Column("trades_force_closed", sa.Integer(), nullable=False),
        sa.Column("equity_quote", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("one_r_quote", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("usd_eur_rate", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("realized_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("max_drawdown_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("max_open_risk_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("total_fees_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("total_slippage_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("safety_oracle", sa.String(length=40), nullable=False),
        sa.Column("skipped_by_reason", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["hypothesis_id"], ["quant_hypotheses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quant_strategy_runs_hypothesis_id"), "quant_strategy_runs", ["hypothesis_id"]
    )
    op.create_index(
        op.f("ix_quant_strategy_runs_started_at"), "quant_strategy_runs", ["started_at"]
    )

    op.create_table(
        "quant_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("pool_address", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_usd", sa.Numeric(precision=30, scale=12), nullable=True),
        sa.Column("taken", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["quant_strategy_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_signals_run_id"), "quant_signals", ["run_id"])
    op.create_index("ix_quant_signals_run_taken", "quant_signals", ["run_id", "taken"])

    op.create_table(
        "quant_paper_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("pool_address", sa.String(length=80), nullable=False),
        sa.Column("token_address", sa.String(length=80), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_reason", sa.String(length=60), nullable=False),
        sa.Column("exit_reason", sa.String(length=60), nullable=True),
        sa.Column("risk_r", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("risk_quote", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("units", sa.Numeric(precision=30, scale=8), nullable=False),
        sa.Column("entry_expected_price", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("entry_fill_price", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("stop_price", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("exit_quote_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("fees_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("slippage_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("latency_cost_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("pnl_usd", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("r_multiple", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["quant_strategy_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_paper_trades_opened_at"), "quant_paper_trades", ["opened_at"])
    op.create_index(op.f("ix_quant_paper_trades_run_id"), "quant_paper_trades", ["run_id"])
    op.create_index(
        "ix_quant_paper_trades_run_pool", "quant_paper_trades", ["run_id", "pool_address"]
    )

    op.create_table(
        "quant_paper_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("filled", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=40), nullable=True),
        sa.Column("expected_price", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("market_price", sa.Numeric(precision=30, scale=12), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("units", sa.Numeric(precision=30, scale=8), nullable=False),
        sa.Column("quote_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("slippage_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("latency_cost_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("fee_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("exit_haircut_applied", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["quant_paper_trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quant_paper_fills_trade_id"), "quant_paper_fills", ["trade_id"])


def downgrade() -> None:
    op.drop_table("quant_paper_fills")
    op.drop_table("quant_paper_trades")
    op.drop_table("quant_signals")
    op.drop_table("quant_strategy_runs")
    op.drop_table("quant_hypotheses")
