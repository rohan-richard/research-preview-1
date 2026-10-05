"""push

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01 12:28:08.303394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('link', sa.Text(), nullable=False),
    sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.Text(), server_default='scheduled', nullable=False),
    sa.Column('skip_reason', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'idempotency_key')
    )
    op.create_index('ix_notifications_status_scheduled', 'notifications', ['status', 'scheduled_for'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('push_devices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('apns_token', sa.Text(), nullable=True),
    sa.Column('apns_environment', sa.Text(), nullable=True),
    sa.Column('web_endpoint', sa.Text(), nullable=True),
    sa.Column('web_p256dh', sa.Text(), nullable=True),
    sa.Column('web_auth', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('failure_count', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('web_endpoint')
    )
    op.create_index(op.f('ix_push_devices_user_id'), 'push_devices', ['user_id'], unique=False)
    op.create_table('notification_deliveries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('notification_id', sa.Uuid(), nullable=False),
    sa.Column('device_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['push_devices.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_deliveries_notification_id'), 'notification_deliveries', ['notification_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_deliveries_notification_id'), table_name='notification_deliveries')
    op.drop_table('notification_deliveries')
    op.drop_index(op.f('ix_push_devices_user_id'), table_name='push_devices')
    op.drop_table('push_devices')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index('ix_notifications_status_scheduled', table_name='notifications')
    op.drop_table('notifications')
