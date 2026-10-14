from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.platform import AgentRun, RunEvent
from app.security.auth import get_current_user
from app.application.chat import persist_run_event, stream_run_events

router = APIRouter(prefix='/runs', tags=['Agent 执行记录'])

@router.get('')
async def list_runs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.created_at.desc()).limit(50))).all()

@router.get('/{run_id}')
async def get_run(run_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id))
    if not run:
        raise HTTPException(404, '执行记录不存在')
    events = (await db.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence))).all()
    return {'run': run, 'events': [event.payload for event in events]}

@router.get('/{run_id}/events')
async def subscribe_run(run_id: str, after_sequence: int = 0, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id))
    if not run:
        raise HTTPException(404, '执行记录不存在')
    await db.close()
    return StreamingResponse(stream_run_events(run_id, after_sequence), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@router.post('/{run_id}/cancel')
async def cancel_run(run_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id))
    if not run:
        raise HTTPException(404, '执行记录不存在')
    if run.status in {'queued', 'paused'}:
        result = await db.execute(update(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user.id, AgentRun.status.in_(['queued', 'paused'])
        ).values(status='cancelled', finished_at=datetime.utcnow()))
        cancelled = result.rowcount == 1
        if not cancelled:
            await db.execute(update(AgentRun).where(
                AgentRun.id == run_id, AgentRun.user_id == user.id, AgentRun.status == 'running'
            ).values(status='cancel_requested'))
        await db.commit()
        if cancelled:
            await persist_run_event(run_id, {'type': 'RUN_ERROR', 'code': 'CANCELLED', 'message': '用户已停止执行'})
    elif run.status == 'running':
        await db.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id,
            AgentRun.status == 'running').values(status='cancel_requested'))
        await db.commit()
    await db.refresh(run)
    return {'run_id': run_id, 'status': run.status}

