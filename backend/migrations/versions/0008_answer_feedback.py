"""Add answer feedback evidence, review events, and explicit reviewer role."""
from alembic import op
import sqlalchemy as sa

revision = '0008_answer_feedback'
down_revision = '0007_agent_background_runs'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('role', sa.String(20),
        sa.CheckConstraint("role IN ('user','feedback_admin')", name='ck_user_role'),
        server_default='user', nullable=False))
    op.create_table('answer_feedback',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('reporter_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reporter_name_snapshot', sa.String(50), nullable=False),
        sa.Column('assistant_message_key', sa.String(36), nullable=False),
        sa.Column('assistant_message_id', sa.String(36), sa.ForeignKey('messages.id', ondelete='SET NULL')),
        sa.Column('question_message_id', sa.String(36), sa.ForeignKey('messages.id', ondelete='SET NULL')),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='SET NULL')),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('agent_runs.id', ondelete='SET NULL')),
        sa.Column('workspace_id', sa.String(36)),
        sa.Column('question_snapshot', sa.Text(), nullable=False),
        sa.Column('evidence_snapshot', sa.JSON(), nullable=False),
        sa.Column('reason', sa.String(32), nullable=False),
        sa.Column('user_comment', sa.Text(), server_default='', nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('processing_note', sa.Text(), server_default='', nullable=False),
        sa.Column('last_handled_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('last_handled_at', sa.DateTime()),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('reporter_id', 'assistant_message_key'),
        sa.CheckConstraint("status IN ('pending','resolved')", name='ck_feedback_status'),
        sa.CheckConstraint("reason IN ('data_error','irrelevant','citation_error','presentation_error','other')", name='ck_feedback_reason'),
        sa.CheckConstraint('version >= 1', name='ck_feedback_version'))
    op.create_index('ix_feedback_created', 'answer_feedback', ['created_at', 'id'])
    op.create_index('ix_feedback_status_created', 'answer_feedback', ['status', 'created_at', 'id'])
    op.create_index('ix_feedback_reporter_created', 'answer_feedback', ['reporter_id', 'created_at'])
    op.create_table('answer_feedback_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('feedback_id', sa.String(36), sa.ForeignKey('answer_feedback.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('actor_name_snapshot', sa.String(50), nullable=False),
        sa.Column('from_status', sa.String(20)),
        sa.Column('to_status', sa.String(20), nullable=False),
        sa.Column('old_note', sa.Text(), server_default='', nullable=False),
        sa.Column('new_note', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('feedback_id', 'version'))


def downgrade():
    op.drop_table('answer_feedback_events')
    op.drop_table('answer_feedback')
    # SQLite stores the role CHECK inline; PostgreSQL requires explicit constraint removal.
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('ck_user_role', 'users', type_='check')
    op.drop_column('users', 'role')
