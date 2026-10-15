import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.platform import AgentRun
from app.services.resource_scope import get_workspace
from app.schemas.conversation import ConversationCreate, ConversationUpdate, ConversationOut, MessageOut
from app.security.auth import get_current_user

router = APIRouter(prefix="/sessions", tags=["会话管理"])


def conversation_output(conv):
    return ConversationOut(id=conv.id, title=conv.title, model=conv.model,
        workspace_id=conv.workspace_id,
        scope_version=conv.scope_version, is_pinned=conv.is_pinned,
        created_at=conv.created_at, updated_at=conv.updated_at)

@router.get("", response_model=List[ConversationOut])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.is_pinned.desc(), Conversation.updated_at.desc())
    res = await db.execute(stmt)
    convs = res.scalars().all()

    return [conversation_output(conv) for conv in convs]

@router.post("", response_model=ConversationOut)
async def create_session(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workspace = await get_workspace(db, current_user.id, payload.workspace_id)
    conv = Conversation(
        workspace_id=payload.workspace_id,
        user_id=current_user.id,
        title=payload.title or "新建对话",
        model=payload.model or "",
        is_pinned=bool(payload.is_pinned) if payload.is_pinned is not None else False
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return conversation_output(conv)

@router.get("/{session_id}", response_model=ConversationOut)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(
        and_(Conversation.id == session_id, Conversation.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    return conversation_output(conv)

@router.put("/{session_id}", response_model=ConversationOut)
async def update_session(
    session_id: str,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(
        and_(Conversation.id == session_id, Conversation.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    if payload.title is not None:
        conv.title = payload.title
    if payload.model is not None:
        conv.model = payload.model
    if payload.is_pinned is not None:
        conv.is_pinned = payload.is_pinned

    await db.commit()
    return conversation_output(conv)

@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(
        and_(Conversation.id == session_id, Conversation.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    active_run = await db.scalar(select(AgentRun.id).where(
        AgentRun.conversation_id == session_id,
        AgentRun.status.in_(['queued', 'running', 'cancel_requested', 'paused'])).limit(1))
    if active_run:
        raise HTTPException(status_code=409, detail="会话仍有 Agent 任务运行，请先停止任务后再删除")

    await db.delete(conv)
    await db.commit()
    return {"message": "会话已删除", "session_id": session_id}

@router.get("/{session_id}/messages", response_model=List[MessageOut])
async def list_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 校验归属
    c_stmt = select(Conversation).where(
        and_(Conversation.id == session_id, Conversation.user_id == current_user.id)
    )
    c_res = await db.execute(c_stmt)
    if not c_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="会话不存在")

    stmt = select(Message).where(
        Message.conversation_id == session_id
    ).order_by(Message.created_at.asc())
    res = await db.execute(stmt)
    msgs = res.scalars().all()

    output = []
    for m in msgs:
        output.append(MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            tool_calls=json.loads(m.tool_calls) if m.tool_calls else None,
            created_at=m.created_at
        ))
    return output
