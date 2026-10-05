"""journeys and habits

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01 12:15:21.586131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('journeys',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('why', sa.Text(), server_default='', nullable=False),
    sa.Column('plan_goal_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_goal_id'], ['care_plan_goals.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_journeys_user_id'), 'journeys', ['user_id'], unique=False)
    op.create_table('habits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('journey_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('cue', sa.Text(), nullable=True),
    sa.Column('barrier', sa.Text(), nullable=True),
    sa.Column('fallback', sa.Text(), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('pace', sa.Text(), server_default='small_steps', nullable=False),
    sa.Column('reminder_time', sa.Time(), nullable=True),
    sa.Column('paused', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('origin', sa.Text(), server_default='patient', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_habits_journey_id'), 'habits', ['journey_id'], unique=False)
    op.create_index(op.f('ix_habits_user_id'), 'habits', ['user_id'], unique=False)
    op.create_table('habit_check_ins',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('habit_id', sa.Uuid(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('outcome', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('plan_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['habit_id'], ['habits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('habit_id', 'date')
    )
    op.create_foreign_key('fk_care_plan_goals_journey_id', 'care_plan_goals', 'journeys', ['journey_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    # WARNING: constraint name is None; this directive will fail as
    # rendered.  Add a name, or use a naming convention; see
    # https://alembic.sqlalchemy.org/en/latest/naming.html
    op.drop_constraint('fk_care_plan_goals_journey_id', 'care_plan_goals', type_='foreignkey')
    op.drop_table('habit_check_ins')
    op.drop_index(op.f('ix_habits_user_id'), table_name='habits')
    op.drop_index(op.f('ix_habits_journey_id'), table_name='habits')
    op.drop_table('habits')
    op.drop_index(op.f('ix_journeys_user_id'), table_name='journeys')
    op.drop_table('journeys')
