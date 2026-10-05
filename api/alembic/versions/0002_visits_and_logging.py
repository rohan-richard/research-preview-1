"""visits and logging

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 11:48:36.488597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('appointments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Text(), server_default='patient', nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=True),
    sa.Column('clinician', sa.Text(), nullable=True),
    sa.Column('organization', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='confirmed', nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('join_link', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_appointments_user_starts', 'appointments', ['user_id', 'starts_at'], unique=False)
    op.create_table('idempotency_keys',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('route', sa.Text(), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'key')
    )
    op.create_table('logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('taken_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), server_default='patient', nullable=False),
    sa.Column('medication_id', sa.Uuid(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_logs_user_kind_taken', 'logs', ['user_id', 'kind', 'taken_at'], unique=False)
    op.create_table('guide_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('resolved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('added_from', sa.Text(), nullable=True),
    sa.Column('appointment_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guide_items_user_id'), 'guide_items', ['user_id'], unique=False)
    op.create_table('visit_preps',
    sa.Column('appointment_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('step', sa.Text(), server_default='focus', nullable=False),
    sa.Column('goal', sa.Text(), server_default='', nullable=False),
    sa.Column('changes', sa.Text(), server_default='', nullable=False),
    sa.Column('medication_concerns', sa.Text(), server_default='', nullable=False),
    sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('practical_needs', sa.Text(), server_default='', nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_text', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('appointment_id')
    )
    op.create_index(op.f('ix_visit_preps_user_id'), 'visit_preps', ['user_id'], unique=False)
    op.create_table('visit_prep_logs',
    sa.Column('appointment_id', sa.Uuid(), nullable=False),
    sa.Column('log_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['visit_preps.appointment_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_id'], ['logs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('appointment_id', 'log_id')
    )


def downgrade() -> None:
    op.drop_table('visit_prep_logs')
    op.drop_index(op.f('ix_visit_preps_user_id'), table_name='visit_preps')
    op.drop_table('visit_preps')
    op.drop_index(op.f('ix_guide_items_user_id'), table_name='guide_items')
    op.drop_table('guide_items')
    op.drop_index('ix_logs_user_kind_taken', table_name='logs')
    op.drop_table('logs')
    op.drop_table('idempotency_keys')
    op.drop_index('ix_appointments_user_starts', table_name='appointments')
    op.drop_table('appointments')
