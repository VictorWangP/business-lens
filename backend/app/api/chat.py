from ag_ui.core import RunAgentInput
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.user import User
from app.models.conversation import Bookmark
from app.schemas.chat import ChatRequest, BookmarkCreate, BookmarkOut, BookmarkToggleOut
from app.security.auth import get_current_user
from app.config import settings

router = APIRouter(prefix="/chat", tags=["聊天与问数"])

@router.post('/stream')
async def chat_stream(payload: 'RunAgentInput', current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.application.chat import prepare_chat, stream_run_events
    from app.models.conversation import Conversation, Message
    from app.models.platform import AgentRun, RunEvent
    from app.services.resource_scope import get_workspace, validate_scope
    from sqlalchemy import func
    import json
    import uuid

    # A caller cannot inject model history, tools, state, or LangGraph commands.
    if set(payload.forwarded_props or {}) - {'workspace_id','model'}:
        raise HTTPException(422, '业务范围由服务端管理')
    if payload.tools or payload.context or payload.state:
        raise HTTPException(422, '会话状态和工具由服务端管理')
    if len(payload.thread_id) > 36 or len(payload.run_id) > 36:
        raise HTTPException(422, '会话或运行 ID 无效')
    conversation = await db.get(Conversation, payload.thread_id)
    if conversation and conversation.user_id != current_user.id:
        raise HTTPException(404, '会话不存在')
    latest = next((m for m in reversed(payload.messages) if m.role == 'user'), None)
    if latest is None or not latest.id or len(latest.id)>36 or not isinstance(latest.content, str) or not latest.content.strip():
        raise HTTPException(422, '请提供文本问题')
    user_message = await db.get(Message, latest.id)
    if user_message and (user_message.user_id != current_user.id or user_message.conversation_id != payload.thread_id):
        raise HTTPException(404, '消息不存在')
    run = None
    after_sequence = 0
    if user_message and user_message.content == latest.content:
        candidates = (await db.scalars(select(AgentRun).where(AgentRun.conversation_id == payload.thread_id,
            AgentRun.user_id == current_user.id).order_by(AgentRun.created_at.desc()))).all()
        run = next((r for r in candidates if r.input_payload.get('user_message_id') == latest.id), None)
    if payload.resume:
        incoming = [item.model_dump(mode='json', by_alias=True) for item in payload.resume]
        if not run:
            raise HTTPException(409, '该会话没有可恢复的暂停任务')
        workspace = await get_workspace(db, current_user.id, run.workspace_id)
        if workspace.version != run.scope_version:
            raise HTTPException(409, '业务空间已更新，请停止暂停的任务并重新提问')
        await validate_scope(db, current_user.id, run.resource_scope['source_ids'])
        if run.status != 'paused':
            if run.input_payload.get('resume') != incoming:
                raise HTTPException(409, '该会话没有可恢复的暂停任务')
        else:
            from jsonschema import validate, ValidationError
            saved = await db.get(Message, run.assistant_message_id)
            interrupts = json.loads(saved.tool_calls or '{}').get('interrupts', [])
            expected = {item['id']: item for item in interrupts}
            if len(incoming) != len(expected) or {item['interruptId'] for item in incoming} != expected.keys():
                raise HTTPException(422, '恢复请求必须覆盖当前全部暂停项')
            for item in incoming:
                if item['status'] != 'resolved':
                    raise HTTPException(422, '取消暂停任务请使用停止操作')
                try:
                    validate(item.get('payload'), expected[item['interruptId']].get('responseSchema') or {'type':'string','minLength':1,'maxLength':2000})
                except ValidationError:
                    raise HTTPException(422, '补充条件格式无效')
            after_sequence = await db.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run.id)) or 0
            # Official runtime creates a new assistant message when a paused run
            # continues. Archive that segment under a new stable server message ID.
            calls = json.loads(saved.tool_calls or '{}')
            calls['status'] = 'resumed'
            saved.tool_calls = json.dumps(calls, ensure_ascii=False)
            continued = Message(user_id=current_user.id, conversation_id=run.conversation_id,
                scope_version=run.scope_version, role='assistant', content='',
                tool_calls=json.dumps({**calls, 'status':'queued'}, ensure_ascii=False))
            db.add(continued)
            await db.flush()
            updated = {**run.input_payload, 'event_offset': after_sequence, 'resume': incoming}
            from sqlalchemy import update
            result = await db.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == 'paused')
                .values(status='queued', input_payload=updated, assistant_message_id=continued.id))
            if result.rowcount != 1:
                await db.rollback()
                raise HTTPException(409, '暂停任务状态已更新，请刷新后继续')
            await db.commit()
            await db.refresh(run)
    elif not run:
        request = ChatRequest(conversation_id=conversation.id if conversation else None,
            workspace_id=(payload.forwarded_props or {}).get('workspace_id'),
            query=latest.content, model=(payload.forwarded_props or {}).get('model'))
        user_id = current_user.id
        try:
            run = await prepare_chat(db, user_id, request, thread_id=payload.thread_id,
                run_id=payload.run_id, user_message_id=latest.id if not user_message else str(uuid.uuid4()))
        except IntegrityError:
            await db.rollback()
            run = await db.scalar(select(AgentRun).where(AgentRun.id == payload.run_id,
                AgentRun.user_id == user_id, AgentRun.conversation_id == payload.thread_id))
            if not run or run.input_payload.get('query') != latest.content:
                raise HTTPException(409, '会话已有活动任务或请求 ID 冲突')
    if settings.TASK_BACKEND == 'celery' and run.status == 'queued':
        from app.workers.tasks import run_agent
        run_agent.delay(run.id)
    await db.close()
    return StreamingResponse(stream_run_events(run.id, public_run_id=payload.run_id), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'X-Run-Id': run.id})

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

