"""Persist Agent inputs and worker leases for background execution."""
from alembic import op
import sqlalchemy as sa

revision = '0007_agent_background_runs'
down_revision = '0006_workspace_binding'
branch_labels = None
depends_on = None


def upgrade():
    # Runs from the request-bound implementation cannot be resumed by the new Worker.
    op.execute(sa.text("UPDATE agent_runs SET status='failed', error='版本升级后旧执行未恢复，请重新发起任务', finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running','cancel_requested')"))
    op.add_column('agent_runs', sa.Column('input_payload', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('agent_runs', sa.Column('assistant_message_id', sa.String(36), nullable=True))
    op.add_column('agent_runs', sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('agent_runs', sa.Column('lease_expires_at', sa.DateTime(), nullable=True))
    op.create_index('ix_agent_runs_status', 'agent_runs', ['status'])
    op.create_index('ix_agent_runs_assistant_message_id', 'agent_runs', ['assistant_message_id'])
    op.create_index('ix_agent_runs_lease_expires_at', 'agent_runs', ['lease_expires_at'])
    op.create_index('uq_agent_runs_active_conversation', 'agent_runs', ['conversation_id'], unique=True,
        sqlite_where=sa.text("status IN ('queued','running','cancel_requested')"),
        postgresql_where=sa.text("status IN ('queued','running','cancel_requested')"))


def downgrade():
    op.drop_index('uq_agent_runs_active_conversation', table_name='agent_runs')
    op.drop_index('ix_agent_runs_lease_expires_at', table_name='agent_runs')
    op.drop_index('ix_agent_runs_assistant_message_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_status', table_name='agent_runs')
    op.drop_column('agent_runs', 'lease_expires_at')
    op.drop_column('agent_runs', 'attempts')
    op.drop_column('agent_runs', 'assistant_message_id')
    op.drop_column('agent_runs', 'input_payload')
