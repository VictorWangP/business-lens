"""Local-first data sources. Existing registered PostgreSQL sources retain their kind."""
from alembic import op
import sqlalchemy as sa
revision='0002_local_backend'
down_revision='0001_platform'
branch_labels=None
depends_on=None

def upgrade():
    columns={c['name'] for c in sa.inspect(op.get_bind()).get_columns('data_sources')}
    if 'kind' not in columns:
        op.add_column('data_sources',sa.Column('kind',sa.String(30),nullable=False,server_default='postgresql'))

    op.execute(sa.text("UPDATE documents SET status='needs_reindex', progress=0, error_msg='索引格式已升级，请重建索引' WHERE active_version='' AND status IN ('ready','parsing','indexing','queued')"))
    if op.get_bind().dialect.name == 'sqlite':
        from app.infrastructure.lexical_index import install
        install(op.get_bind())

def downgrade():
    raise RuntimeError('请使用备份恢复，避免丢失数据源类型信息')
