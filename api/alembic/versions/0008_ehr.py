"""ehr

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01 13:31:10.179566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('webhook_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('signature_verified', sa.Boolean(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default='received', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'external_id')
    )
    op.create_table('ehr_connections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Text(), server_default='fasten', nullable=False),
    sa.Column('org_connection_id', sa.Text(), nullable=False),
    sa.Column('organization', sa.Text(), nullable=False),
    sa.Column('platform_type', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('scope', sa.Text(), nullable=True),
    sa.Column('consent_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'org_connection_id')
    )
    op.create_index(op.f('ix_ehr_connections_user_id'), 'ehr_connections', ['user_id'], unique=False)
    op.create_table('ehr_sync_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('connection_id', sa.Uuid(), nullable=False),
    sa.Column('external_task_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='requested', nullable=False),
    sa.Column('resource_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['ehr_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ehr_sync_jobs_connection_id'), 'ehr_sync_jobs', ['connection_id'], unique=False)
    op.create_table('fhir_resources',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('connection_id', sa.Uuid(), nullable=False),
    sa.Column('resource_type', sa.Text(), nullable=False),
    sa.Column('fhir_id', sa.Text(), nullable=False),
    sa.Column('version_id', sa.Text(), nullable=True),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resource', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sync_job_id', sa.Uuid(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ehr_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sync_job_id'], ['ehr_sync_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'resource_type', 'fhir_id')
    )
    op.create_index('ix_fhir_resources_user_type', 'fhir_resources', ['user_id', 'resource_type'], unique=False)
    op.create_table('allergies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('criticality', sa.Text(), nullable=True),
    sa.Column('reaction', sa.Text(), nullable=True),
    sa.Column('clinical_status', sa.Text(), nullable=False),
    sa.Column('recorded_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_allergies_fhir_resource_id'), 'allergies', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_allergies_user_id'), 'allergies', ['user_id'], unique=False)
    op.create_table('care_team_members',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=True),
    sa.Column('organization', sa.Text(), nullable=True),
    sa.Column('npi', sa.Text(), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_care_team_members_fhir_resource_id'), 'care_team_members', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_care_team_members_user_id'), 'care_team_members', ['user_id'], unique=False)
    op.create_table('conditions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('clinical_status', sa.Text(), nullable=False),
    sa.Column('onset_date', sa.Date(), nullable=True),
    sa.Column('abatement_date', sa.Date(), nullable=True),
    sa.Column('recorded_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conditions_fhir_resource_id'), 'conditions', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_conditions_user_id'), 'conditions', ['user_id'], unique=False)
    op.create_table('encounters',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('class', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=True),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('practitioner', sa.Text(), nullable=True),
    sa.Column('organization', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_encounters_fhir_resource_id'), 'encounters', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_encounters_user_id'), 'encounters', ['user_id'], unique=False)
    op.create_index('ix_encounters_user_start', 'encounters', ['user_id', 'start_at'], unique=False)
    op.create_table('lab_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('performer', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lab_reports_fhir_resource_id'), 'lab_reports', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_lab_reports_user_id'), 'lab_reports', ['user_id'], unique=False)
    op.create_table('medications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('dose_text', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('prescriber', sa.Text(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('refills_allowed', sa.Integer(), nullable=True),
    sa.Column('days_supply', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_medications_fhir_resource_id'), 'medications', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_medications_user_id'), 'medications', ['user_id'], unique=False)
    op.create_table('lab_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('report_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('value_number', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('value_text', sa.Text(), nullable=True),
    sa.Column('unit', sa.Text(), nullable=True),
    sa.Column('range_low', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('range_high', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('interpretation', sa.Text(), nullable=True),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['report_id'], ['lab_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lab_results_fhir_resource_id'), 'lab_results', ['fhir_resource_id'], unique=False)
    op.create_index('ix_lab_results_user_code_effective', 'lab_results', ['user_id', 'code', 'effective_at'], unique=False)
    op.create_index(op.f('ix_lab_results_user_id'), 'lab_results', ['user_id'], unique=False)
    op.create_table('medication_fills',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fhir_resource_id', sa.Uuid(), nullable=False),
    sa.Column('code_system', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('display', sa.Text(), nullable=True),
    sa.Column('medication_id', sa.Uuid(), nullable=False),
    sa.Column('dispensed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('days_supply', sa.Integer(), nullable=True),
    sa.Column('pharmacy', sa.Text(), nullable=True),
    sa.Column('expected_refill_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fhir_resource_id'], ['fhir_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['medication_id'], ['medications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_medication_fills_fhir_resource_id'), 'medication_fills', ['fhir_resource_id'], unique=False)
    op.create_index(op.f('ix_medication_fills_medication_id'), 'medication_fills', ['medication_id'], unique=False)
    op.create_index(op.f('ix_medication_fills_user_id'), 'medication_fills', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_medication_fills_user_id'), table_name='medication_fills')
    op.drop_index(op.f('ix_medication_fills_medication_id'), table_name='medication_fills')
    op.drop_index(op.f('ix_medication_fills_fhir_resource_id'), table_name='medication_fills')
    op.drop_table('medication_fills')
    op.drop_index(op.f('ix_lab_results_user_id'), table_name='lab_results')
    op.drop_index('ix_lab_results_user_code_effective', table_name='lab_results')
    op.drop_index(op.f('ix_lab_results_fhir_resource_id'), table_name='lab_results')
    op.drop_table('lab_results')
    op.drop_index(op.f('ix_medications_user_id'), table_name='medications')
    op.drop_index(op.f('ix_medications_fhir_resource_id'), table_name='medications')
    op.drop_table('medications')
    op.drop_index(op.f('ix_lab_reports_user_id'), table_name='lab_reports')
    op.drop_index(op.f('ix_lab_reports_fhir_resource_id'), table_name='lab_reports')
    op.drop_table('lab_reports')
    op.drop_index('ix_encounters_user_start', table_name='encounters')
    op.drop_index(op.f('ix_encounters_user_id'), table_name='encounters')
    op.drop_index(op.f('ix_encounters_fhir_resource_id'), table_name='encounters')
    op.drop_table('encounters')
    op.drop_index(op.f('ix_conditions_user_id'), table_name='conditions')
    op.drop_index(op.f('ix_conditions_fhir_resource_id'), table_name='conditions')
    op.drop_table('conditions')
    op.drop_index(op.f('ix_care_team_members_user_id'), table_name='care_team_members')
    op.drop_index(op.f('ix_care_team_members_fhir_resource_id'), table_name='care_team_members')
    op.drop_table('care_team_members')
    op.drop_index(op.f('ix_allergies_user_id'), table_name='allergies')
    op.drop_index(op.f('ix_allergies_fhir_resource_id'), table_name='allergies')
    op.drop_table('allergies')
    op.drop_index('ix_fhir_resources_user_type', table_name='fhir_resources')
    op.drop_table('fhir_resources')
    op.drop_index(op.f('ix_ehr_sync_jobs_connection_id'), table_name='ehr_sync_jobs')
    op.drop_table('ehr_sync_jobs')
    op.drop_index(op.f('ix_ehr_connections_user_id'), table_name='ehr_connections')
    op.drop_table('ehr_connections')
    op.drop_table('webhook_events')
