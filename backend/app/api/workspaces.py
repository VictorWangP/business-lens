import json
import uuid
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from app.database import get_db
from app.security.auth import get_current_user
from app.models.conversation import BusinessWorkspace
from app.models.knowledge import KnowledgeBase
from app.models.platform import DataSource
from app.services.resource_scope import get_workspace, validate_scope

router = APIRouter(prefix='/workspaces', tags=['业务空间'])

class WorkspaceWrite(BaseModel):
    version: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    kb_ids: list[str] = Field(default_factory=list, max_length=30)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


async def outputs(db, user_id, items):
    kbs = set((await db.scalars(select(KnowledgeBase.id).where(KnowledgeBase.user_id == user_id))).all())
    sources = set((await db.scalars(select(DataSource.id).where(DataSource.user_id == user_id))).all())
    result = []
    for workspace in items:
        kb_ids, source_ids = json.loads(workspace.kb_ids), json.loads(workspace.source_ids)
        missing_kbs, missing_sources = sorted(set(kb_ids) - kbs), sorted(set(source_ids) - sources)
        result.append(dict(id=workspace.id, name=workspace.name, version=workspace.version,
                           kb_ids=kb_ids, source_ids=source_ids,
                           unavailable_kb_ids=missing_kbs, unavailable_source_ids=missing_sources,
                           status='invalid' if missing_kbs or missing_sources else 'ready' if kb_ids or source_ids else 'empty'))
    return result


@router.get('')
async def list_workspaces(user=Depends(get_current_user), db=Depends(get_db)):
    items = (await db.scalars(select(BusinessWorkspace).where(BusinessWorkspace.user_id == user.id)
                              .order_by(BusinessWorkspace.name, BusinessWorkspace.id))).all()
    if not items:
        workspace = BusinessWorkspace(id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'rag-workspace:' + user.id)), user_id=user.id, name='默认业务空间', kb_ids='[]', source_ids='[]')
        db.add(workspace)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            workspace = await get_workspace(db, user.id, str(uuid.uuid5(uuid.NAMESPACE_URL, 'rag-workspace:' + user.id)))
        items = [workspace]
    return await outputs(db, user.id, items)


@router.post('')
async def create_workspace(payload: WorkspaceWrite, user=Depends(get_current_user), db=Depends(get_db)):
    await validate_scope(db, user.id, payload.kb_ids, payload.source_ids)
    workspace = BusinessWorkspace(user_id=user.id, name=payload.name.strip(),
                                  kb_ids=json.dumps(payload.kb_ids), source_ids=json.dumps(payload.source_ids))
    db.add(workspace)
    await db.commit()
    return (await outputs(db, user.id, [workspace]))[0]


@router.put('/{workspace_id}')
async def update_workspace(workspace_id: str, payload: WorkspaceWrite,
                           user=Depends(get_current_user), db=Depends(get_db)):
    workspace = await get_workspace(db, user.id, workspace_id)
    await validate_scope(db, user.id, payload.kb_ids, payload.source_ids)
    if payload.version is not None and payload.version != workspace.version:
        raise HTTPException(409, '业务空间已被更新，请刷新配置后重新编辑')
    kb_ids, source_ids = sorted(set(payload.kb_ids)), sorted(set(payload.source_ids))
    changed = kb_ids != sorted(set(json.loads(workspace.kb_ids))) or source_ids != sorted(set(json.loads(workspace.source_ids)))
    result = await db.execute(update(BusinessWorkspace).where(
        BusinessWorkspace.id == workspace.id, BusinessWorkspace.version == workspace.version).values(
        name=payload.name.strip(), kb_ids=json.dumps(kb_ids), source_ids=json.dumps(source_ids),
        version=workspace.version + int(changed)))
    if result.rowcount != 1:
        raise HTTPException(409, '业务空间已被更新，请刷新配置后重新编辑')
    await db.commit()
    await db.refresh(workspace)
    return (await outputs(db, user.id, [workspace]))[0]
