from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.frequent import QuestionGroup, QuestionRecord
from app.infrastructure.embeddings import EmbeddingProvider
from app.security.auth import get_current_user
from app.services.frequent_service import list_questions, PROFILE_CHANGED

router = APIRouter(prefix='/frequent-questions', tags=['常问问题'])


async def reset_required(db, user_id):
    if await db.scalar(select(QuestionRecord.message_id).where(QuestionRecord.user_id == user_id, QuestionRecord.error_code == PROFILE_CHANGED).limit(1)):
        return True
    profiles = set((await db.scalars(select(QuestionGroup.embedding_profile).where(QuestionGroup.user_id == user_id).distinct())).all())
    if profiles:
        try:
            return profiles != {(await EmbeddingProvider.for_user(db, user_id)).profile}
        except ValueError:
            pass
    return False


@router.get('')
async def frequent_questions(workspace_id: str | None = None, source_ids: list[str] = Query(default=[]),
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if workspace_id:
        import json
        from app.services.resource_scope import get_workspace, validate_scope
        workspace = await get_workspace(db, user.id, workspace_id)
        source_ids = json.loads(workspace.source_ids)
        await validate_scope(db, user.id, source_ids)
    return await list_questions(db, user.id, source_ids)


@router.delete('')
async def reset_questions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(QuestionRecord).where(QuestionRecord.user_id == user.id))
    await db.execute(delete(QuestionGroup).where(QuestionGroup.user_id == user.id))
    await db.commit()
    return {'message': '已重置常问统计，从新提问开始累计'}
