"""Remove unused fact memory, synthetic orders and empty knowledge scope keys.

Nonempty legacy tables and changed scopes are exported before any deletion.
The export is private local data, outside the application schema.
"""
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from app.config import settings

revision = '0002_cleanup_legacy'
down_revision = '0001_langgraph'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names())
    archive = {'revision': revision, 'tables': {}, 'resource_scopes': []}
    runs = sa.table('agent_runs', sa.column('id', sa.String), sa.column('resource_scope', sa.JSON))
    for run_id, scope in connection.execute(sa.select(runs.c.id, runs.c.resource_scope)):
        if not isinstance(scope, dict) or 'kb_ids' not in scope:
            continue
        if scope['kb_ids'] != []:
            raise RuntimeError('仍有非空知识库运行范围；请先审查数据再执行清理迁移')
        archive['resource_scopes'].append({'id': run_id, 'resource_scope': scope})

    for name in ('memory_facts', 'sales_orders'):
        if name in existing:
            table = sa.Table(name, sa.MetaData(), autoload_with=connection)
            rows = [dict(row) for row in connection.execute(sa.select(table)).mappings()]
            if rows:
                archive['tables'][name] = {
                    'columns': [{'name': column['name'], 'type': str(column['type']),
                                 'nullable': column['nullable'], 'primary_key': column['primary_key']}
                                for column in inspector.get_columns(name)],
                    'rows': rows,
                }

    if archive['tables'] or archive['resource_scopes']:
        directory = settings.STORAGE_DIR / '.local-backups' / 'cleanup-legacy'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        path = directory / f'{stamp}-{uuid4().hex}.json'
        with open(path, 'x', encoding='utf-8', opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            json.dump(archive, file, ensure_ascii=False, indent=2, default=str)
            file.flush()
            os.fsync(file.fileno())

    for item in archive['resource_scopes']:
        scope = {key: value for key, value in item['resource_scope'].items() if key != 'kb_ids'}
        connection.execute(runs.update().where(runs.c.id == item['id']).values(resource_scope=scope))
    for name in ('memory_facts', 'sales_orders'):
        if name in existing:
            op.drop_table(name)


def downgrade():
    raise RuntimeError('清理迁移不可自动回退；请从迁移前数据库备份恢复')
