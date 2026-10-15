from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.feedback import AnswerFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackUpdate, FeedbackStatus
from app.security.auth import get_current_user, get_feedback_admin
from app.services import feedback_service as service

router = APIRouter(tags=['反馈管理'])


@router.post('/messages/{message_id}/feedback')
async def submit(message_id: str, payload: FeedbackCreate, response: Response,
                 user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record, created = await service.create_feedback(db, user, message_id, payload)
    response.status_code = 201 if created else 200
    return service.summary(record, not created)


@router.get('/sessions/{session_id}/feedback-context')
async def feedback_context(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.feedback_context(db, user, session_id)


@router.get('/feedback')
async def listing(question: str = Query('', max_length=200), user: str = Query('', max_length=100),
                  status: FeedbackStatus | None = None, page: int = Query(1, ge=1), page_size: int = 10,
                  admin: User = Depends(get_feedback_admin), db: AsyncSession = Depends(get_db)):
    if page_size not in {10, 20, 50}:
        raise HTTPException(422, '每页条数只能为 10、20、50')
    conditions = []
    if question.strip():
        conditions.append(AnswerFeedback.question_snapshot.icontains(question.strip(), autoescape=True))
    if user.strip():
        conditions.append(AnswerFeedback.reporter_name_snapshot.icontains(user.strip(), autoescape=True))
    if status:
        conditions.append(AnswerFeedback.status == status)
    total = await db.scalar(select(func.count()).select_from(AnswerFeedback).where(*conditions))
    records = (await db.scalars(select(AnswerFeedback).where(*conditions).order_by(
        AnswerFeedback.created_at.desc(), AnswerFeedback.id.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {'items': [service.list_item(record) for record in records], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/feedback/{feedback_id}')
async def get_detail(feedback_id: str, admin: User = Depends(get_feedback_admin), db: AsyncSession = Depends(get_db)):
    return await service.detail(db, await service.get_record(db, feedback_id))


@router.patch('/feedback/{feedback_id}')
async def process(feedback_id: str, payload: FeedbackUpdate,
                  admin: User = Depends(get_feedback_admin), db: AsyncSession = Depends(get_db)):
    return await service.update_feedback(db, admin, await service.get_record(db, feedback_id), payload)
