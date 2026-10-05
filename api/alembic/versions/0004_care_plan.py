"""care plan

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01 12:11:52.969565

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('care_plans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('author', sa.Text(), nullable=True),
    sa.Column('organization', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_care_plans_user_id'), 'care_plans', ['user_id'], unique=False)
    op.create_table('care_plan_activities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('care_plan_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='not_started', nullable=False),
    sa.Column('scheduled_for', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['care_plan_id'], ['care_plans.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_care_plan_activities_care_plan_id'), 'care_plan_activities', ['care_plan_id'], unique=False)
    op.create_table('care_plan_goals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('care_plan_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('target_code', sa.Text(), nullable=True),
    sa.Column('target_value', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('target_unit', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('journey_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['care_plan_id'], ['care_plans.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_care_plan_goals_care_plan_id'), 'care_plan_goals', ['care_plan_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_care_plan_goals_care_plan_id'), table_name='care_plan_goals')
    op.drop_table('care_plan_goals')
    op.drop_index(op.f('ix_care_plan_activities_care_plan_id'), table_name='care_plan_activities')
    op.drop_table('care_plan_activities')
    op.drop_index(op.f('ix_care_plans_user_id'), table_name='care_plans')
    op.drop_table('care_plans')
