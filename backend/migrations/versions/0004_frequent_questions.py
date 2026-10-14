"""User-scoped frequent questions and durable queue."""
from alembic import op
import sqlalchemy as sa

revision = '0004_frequent_questions'
down_revision = '0003_knowledge_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('question_groups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('representative_question', sa.Text(), nullable=False),
        sa.Column('representative_asked_at', sa.DateTime(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=False),
        sa.Column('embedding_profile', sa.String(64), nullable=False))
    op.create_index('ix_question_groups_user_scope', 'question_groups', ['user_id', 'scope_key'])
    op.create_table('question_records',
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('kb_ids', sa.JSON(), nullable=False),
        sa.Column('source_ids', sa.JSON(), nullable=False),
        sa.Column('group_id', sa.String(36), sa.ForeignKey('question_groups.id', ondelete='SET NULL')),
        sa.Column('normalized_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending','processing','completed','skipped','failed')", name='ck_question_record_status'))
    op.create_index('ix_question_records_user_scope_status', 'question_records', ['user_id', 'scope_key', 'status'])
    op.create_index('ix_question_records_status_created', 'question_records', ['status', 'created_at'])
    op.create_index('ix_question_records_group_id', 'question_records', ['group_id'])


def downgrade():
    op.drop_table('question_records')
    op.drop_table('question_groups')
