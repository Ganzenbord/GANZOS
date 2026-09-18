"""Stemprofielen en video's (fase 1)

Twee tabellen die nog ontbraken uit de fundamentlijst. De rest stond er al onder een
andere naam: Skill, MissionTask (= Task), Conversation, ConversationMessage (= Message),
SocialChannel (= ChannelAccount), MemoryEntry en ActivityLogEntry. Zie docs/database.md.

Revision ID: 0002_voice_profiles_and_videos
Revises: 0001_command_center_v2
Create Date: 2026-09-18 08:22:16.567284
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0002_voice_profiles_and_videos'
down_revision = '0001_command_center_v2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('voice_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('embedding', sa.JSON(), nullable=True),
    sa.Column('embedding_model', sa.String(length=190), nullable=True),
    sa.Column('embedding_dim', sa.Integer(), nullable=True),
    sa.Column('sample_seconds', sa.Float(), nullable=True),
    sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voice_profiles_user_id'), 'voice_profiles', ['user_id'], unique=False)
    op.create_table('videos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=True),
    sa.Column('upload_schedule_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=190), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('source_path', sa.Text(), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['channel_id'], ['social_channels.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['upload_schedule_id'], ['upload_schedules.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_videos_channel_id'), 'videos', ['channel_id'], unique=False)
    op.create_index(op.f('ix_videos_external_id'), 'videos', ['external_id'], unique=False)
    op.create_index(op.f('ix_videos_status'), 'videos', ['status'], unique=False)
    op.create_index(op.f('ix_videos_upload_schedule_id'), 'videos', ['upload_schedule_id'], unique=False)
    op.create_index(op.f('ix_videos_user_id'), 'videos', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_videos_user_id'), table_name='videos')
    op.drop_index(op.f('ix_videos_upload_schedule_id'), table_name='videos')
    op.drop_index(op.f('ix_videos_status'), table_name='videos')
    op.drop_index(op.f('ix_videos_external_id'), table_name='videos')
    op.drop_index(op.f('ix_videos_channel_id'), table_name='videos')
    op.drop_table('videos')
    op.drop_index(op.f('ix_voice_profiles_user_id'), table_name='voice_profiles')
    op.drop_table('voice_profiles')
