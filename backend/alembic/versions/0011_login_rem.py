"""Een rem op het raden van wachtwoorden

Eén nieuwe tabel, geen bestaande kolom aangeraakt.

`login_attempts` bewaart mislukte inlogpogingen, zodat ze geteld kunnen worden over een
tijdvenster. Dat was de enige plek waar een geheim onbeperkt geprobeerd kon worden: de
bevestigingslaag had deze rem al (`confirmation_max_failures`), inloggen niet.

Het e-mailadres staat er als sha256-afdruk en niet als tekst. Wie mis tikt is meestal de
eigenaar, maar wie aan het proberen is, vult adressen in van mensen die hier geen gebruiker
zijn — en die adressen bewaren zou betekenen dat Ganz gegevens verzamelt over mensen die er
niets te zoeken hebben. Een afdruk is wél te tellen en niet terug te lezen.

De rijen zijn bedoeld om te verdwijnen: `login_guard.prune_attempts()` gooit ze na een dag
weg. Het tijdvenster waarin ze meetellen is kwartieren.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_login_rem"
down_revision = "0010_quant_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Op alle drie wordt geteld: per adres, per IP, en op tijd. Zonder deze indexen groeit
    # de inlogroute mee met de tabel, en dat is precies de kant die een aanvaller uitbuit.
    op.create_index("ix_login_attempts_email_hash", "login_attempts", ["email_hash"])
    op.create_index("ix_login_attempts_ip_address", "login_attempts", ["ip_address"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_ip_address", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email_hash", table_name="login_attempts")
    op.drop_table("login_attempts")
