"""Persist business workspace defaults and per-session source scope."""
from alembic import op
import sqlalchemy as sa

revision = '0005_resource_scope'
down_revision = '0004_frequent_questions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('business_workspaces',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('kb_ids', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('source_ids', sa.Text(), nullable=False, server_default='[]'))
    op.create_index('ix_business_workspaces_user_id', 'business_workspaces', ['user_id'])
    with op.batch_alter_table('conversations') as batch:
        batch.add_column(sa.Column('source_ids', sa.Text(), nullable=False, server_default='[]'))
        batch.add_column(sa.Column('workspace_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_conversations_workspace', 'business_workspaces', ['workspace_id'], ['id'], ondelete='SET NULL')

    import uuid
    bind = op.get_bind()
    for user_id in bind.execute(sa.text('SELECT id FROM users')).scalars().all():
        workspace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'rag-workspace:' + user_id))
        bind.execute(sa.text("INSERT INTO business_workspaces (id,user_id,name,kb_ids,source_ids) VALUES (:id,:user_id,:name,'[]','[]')"),
                     dict(id=workspace_id, user_id=user_id, name='默认业务空间'))
        bind.execute(sa.text('UPDATE conversations SET workspace_id=:workspace_id WHERE user_id=:user_id'),
                     dict(workspace_id=workspace_id, user_id=user_id))


def downgrade():
    with op.batch_alter_table('conversations') as batch:
        batch.drop_constraint('fk_conversations_workspace', type_='foreignkey')
        batch.drop_column('workspace_id')
        batch.drop_column('source_ids')
    op.drop_table('business_workspaces')
