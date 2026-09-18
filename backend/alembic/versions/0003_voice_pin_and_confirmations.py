"""Stem, pincode en bevestigingen (fase 2)

Drie dingen:

1. `users.tier` mag nu leeg zijn. Leeg betekent: wel bekend, geen toegang — iets anders dan
   `active=False` (uitgezet) en iets anders dan de laagste tier (mag een beetje). Je hebt
   het nodig zodra een stem herkend kan worden: dan wil je "dag Piet" kunnen zeggen zonder
   Piet ergens binnen te laten. Bestaande gebruikers houden hun tier.
2. `users.pin_hash` erbij: de tweede bevestiging vanaf een telefoon of via de stem. Alleen
   de afdruk, nooit de code zelf.
3. `confirmation_requests`: elke tweede bevestiging als rij, zodat achteraf te zien is dát
   er bevestigd is, waarvoor, en hoe vaak het misging — en zodat dezelfde bevestiging niet
   twee keer langs de kassa kan.

Revision ID: 0003_voice_pin_and_confirmations
Revises: 0002_voice_profiles_and_videos
Create Date: 2026-09-18 08:51:45.576161
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0003_voice_pin_and_confirmations'
down_revision = '0002_voice_profiles_and_videos'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('confirmation_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('permission_key', sa.String(length=80), nullable=True),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('origin', sa.String(length=20), nullable=True),
    sa.Column('origin_confidence', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_confirmation_requests_permission_key'), 'confirmation_requests', ['permission_key'], unique=False)
    op.create_index(op.f('ix_confirmation_requests_status'), 'confirmation_requests', ['status'], unique=False)
    op.create_index(op.f('ix_confirmation_requests_user_id'), 'confirmation_requests', ['user_id'], unique=False)
    op.add_column('users', sa.Column('pin_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('pin_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('users', 'tier',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'tier',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('users', 'pin_updated_at')
    op.drop_column('users', 'pin_hash')
    op.drop_index(op.f('ix_confirmation_requests_user_id'), table_name='confirmation_requests')
    op.drop_index(op.f('ix_confirmation_requests_status'), table_name='confirmation_requests')
    op.drop_index(op.f('ix_confirmation_requests_permission_key'), table_name='confirmation_requests')
    op.drop_table('confirmation_requests')
