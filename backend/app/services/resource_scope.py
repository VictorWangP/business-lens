from fastapi import HTTPException
from sqlalchemy import select
from app.models.conversation import BusinessWorkspace
from app.models.knowledge import KnowledgeBase
from app.models.platform import DataSource


async def validate_scope(db, user_id, kb_ids, source_ids):
    for model, ids, label in ((KnowledgeBase, kb_ids, '知识库'), (DataSource, source_ids, '业务数据源')):
        if ids:
            found = set((await db.scalars(select(model.id).where(model.id.in_(ids), model.user_id == user_id))).all())
            if found != set(ids):
                raise HTTPException(403, f'所选{label}已失效或无访问权限，请调整当前范围后重试')


async def get_workspace(db, user_id, workspace_id):
    workspace = await db.scalar(select(BusinessWorkspace).where(
        BusinessWorkspace.id == workspace_id, BusinessWorkspace.user_id == user_id))
    if not workspace:
        raise HTTPException(404, '业务空间不存在')
    return workspace
