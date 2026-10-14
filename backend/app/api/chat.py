from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.models.user import User
from app.models.conversation import Bookmark
from app.schemas.chat import ChatRequest, BookmarkCreate, BookmarkOut, BookmarkToggleOut
from app.security.auth import get_current_user
from app.config import settings

router = APIRouter(prefix="/chat", tags=["聊天与问数"])

@router.post('/stream')
async def chat_stream(payload: ChatRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.application.chat import prepare_chat, stream_run_events
    run = await prepare_chat(db, current_user.id, payload)
    if settings.TASK_BACKEND == 'celery':
        from app.workers.tasks import run_agent
        run_agent.delay(run.id)
    initial = {'type': 'run_started', 'run_id': run.id, 'conversation_id': run.conversation_id,
               'workspace_id': run.workspace_id, 'scope_version': run.scope_version,
               'assistant_message_id': run.assistant_message_id,
               'user_message_id': (run.input_payload or {}).get('user_message_id'),
               'title': (run.input_payload or {}).get('query', '')[:40], 'status': run.status}
    # The response can stay open for the full Agent run. Release the request's
    # database connection before streaming; the event generator owns its reads.
    await db.close()
    return StreamingResponse(stream_run_events(run.id, initial=initial), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@router.get("/bookmarks", response_model=List[BookmarkOut])
async def list_bookmarks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Bookmark).where(Bookmark.user_id == current_user.id).order_by(Bookmark.created_at.desc())
    res = await db.execute(stmt)
    bms = res.scalars().all()
    return [BookmarkOut(id=b.id, content=b.content, created_at=b.created_at) for b in bms]

@router.post("/bookmarks", response_model=BookmarkOut)
async def create_bookmark(
    payload: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    clean_content = payload.content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="收藏内容不能为空")
    
    stmt = select(Bookmark).where(and_(Bookmark.user_id == current_user.id, Bookmark.content == clean_content))
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        return BookmarkOut(id=existing.id, content=existing.content, created_at=existing.created_at)

    bm = Bookmark(user_id=current_user.id, content=clean_content)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    return BookmarkOut(id=bm.id, content=bm.content, created_at=bm.created_at)

@router.post("/bookmarks/toggle", response_model=BookmarkToggleOut)
async def toggle_bookmark(
    payload: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    clean_content = payload.content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="收藏内容不能为空")

    stmt = select(Bookmark).where(and_(Bookmark.user_id == current_user.id, Bookmark.content == clean_content))
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
        return BookmarkToggleOut(bookmarked=False, content=clean_content, id=None)
    else:
        bm = Bookmark(user_id=current_user.id, content=clean_content)
        db.add(bm)
        await db.commit()
        await db.refresh(bm)
        return BookmarkToggleOut(bookmarked=True, content=clean_content, id=bm.id)

@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Bookmark).where(and_(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id))
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="收藏项不存在")

    await db.delete(existing)
    await db.commit()
    return {"message": "已取消收藏", "id": bookmark_id}

