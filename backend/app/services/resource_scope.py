from fastapi import HTTPException
from sqlalchemy import select
from app.models.conversation import BusinessWorkspace
from app.models.platform import DataSource


async def validate_scope(db, user_id, source_ids):
    ids = source_ids
    if ids:
        found = set((await db.scalars(select(DataSource.id).where(DataSource.id.in_(ids), DataSource.user_id == user_id))).all())
        if found != set(ids):
            raise HTTPException(403, '所选业务数据源已失效或无访问权限，请调整当前范围后重试')


async def get_workspace(db, user_id, workspace_id):
    workspace = await db.scalar(select(BusinessWorkspace).where(
        BusinessWorkspace.id == workspace_id, BusinessWorkspace.user_id == user_id))
    if not workspace:
        raise HTTPException(404, '业务空间不存在')
    return workspace
