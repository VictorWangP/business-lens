"""Preserve legacy per-conversation scopes and version workspace executions."""
import json
import uuid
from alembic import op
import sqlalchemy as sa

revision = '0006_workspace_binding'
down_revision = '0005_resource_scope'
branch_labels = None
depends_on = None


def normalized(value):
    return sorted(set(json.loads(value or '[]')))


def upgrade():
    op.add_column('business_workspaces', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('conversations', sa.Column('scope_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('messages', sa.Column('scope_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('agent_runs', sa.Column('workspace_id', sa.String(36), nullable=True))
    op.add_column('agent_runs', sa.Column('scope_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('agent_runs', sa.Column('resource_scope', sa.JSON(), nullable=False, server_default='{}'))
    bind = op.get_bind()
    spaces = {row['id']: dict(row) for row in bind.execute(sa.text('SELECT * FROM business_workspaces')).mappings()}
    groups, counters = {}, {}
    for conv in bind.execute(sa.text('SELECT id,user_id,workspace_id,kb_ids,source_ids FROM conversations ORDER BY id')).mappings().all():
        original = spaces.get(conv['workspace_id'])
        if original and original['user_id'] != conv['user_id']:
            original = None
        kb_ids, source_ids = normalized(conv['kb_ids']), normalized(conv['source_ids'])
        if original and kb_ids == normalized(original['kb_ids']) and source_ids == normalized(original['source_ids']):
            continue
        origin_id = original['id'] if original else ''
        key = (conv['user_id'], origin_id, tuple(kb_ids), tuple(source_ids))
        if key not in groups:
            counters[(conv['user_id'], origin_id)] = counters.get((conv['user_id'], origin_id), 0) + 1
            suffix = counters[(conv['user_id'], origin_id)]
            name = ((original['name'] if original else '默认业务空间')[:70] + f' · 历史范围 {suffix}')
            wid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'rag-legacy-scope:' + json.dumps(key, ensure_ascii=False)))
            bind.execute(sa.text('INSERT INTO business_workspaces (id,user_id,name,kb_ids,source_ids,version) VALUES (:id,:user_id,:name,:kb_ids,:source_ids,1)'),
                         dict(id=wid, user_id=conv['user_id'], name=name, kb_ids=json.dumps(kb_ids), source_ids=json.dumps(source_ids)))
            groups[key] = wid
        bind.execute(sa.text('UPDATE conversations SET workspace_id=:wid WHERE id=:id'), dict(wid=groups[key], id=conv['id']))
    # Scope attribution before this migration is unknown. Keep old messages at version 0:
    # visible in history, but never used as evidence for a versioned workspace request.


def downgrade():
    # The compatible workspaces are intentionally retained to preserve conversation bindings.
    op.drop_column('agent_runs', 'resource_scope')
    op.drop_column('agent_runs', 'scope_version')
    op.drop_column('agent_runs', 'workspace_id')
    op.drop_column('conversations', 'scope_version')
    op.drop_column('messages', 'scope_version')
    op.drop_column('business_workspaces', 'version')
