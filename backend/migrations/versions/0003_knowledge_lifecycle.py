"""Durable cleanup/repair and atomic knowledge-base reindex batches."""
from alembic import op
import sqlalchemy as sa

revision = '0003_knowledge_lifecycle'
down_revision = '0002_local_backend'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('knowledge_bases', sa.Column('index_batch_id', sa.String(36), nullable=False, server_default=''))
    op.add_column('ingestion_jobs', sa.Column('batch_id', sa.String(36), nullable=False, server_default=''))
    op.add_column('ingestion_jobs', sa.Column('embedding_config', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_ingestion_jobs_batch_id', 'ingestion_jobs', ['batch_id'])
    op.create_table('maintenance_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, index=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))

def downgrade():
    raise RuntimeError('请使用备份恢复，避免丢失未完成维护任务')
