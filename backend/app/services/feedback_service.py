import json
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models.conversation import Conversation, Message, BusinessWorkspace
from app.models.platform import AgentRun
from app.models.feedback import AnswerFeedback, AnswerFeedbackEvent
from app.schemas.feedback import FeedbackSnapshotV2
from app.agents.answer import BusinessPresentation

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024


def utc(value):
    return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def summary(record, deduplicated=False):
    return dict(id=record.id, message_id=record.assistant_message_key, status=record.status,
                created_at=utc(record.created_at), deduplicated=deduplicated)


def list_item(record):
    return dict(id=record.id, user={'id': record.reporter_id, 'name': record.reporter_name_snapshot},
                question=record.question_snapshot, created_at=utc(record.created_at),
                status=record.status, version=record.version)


def parsed(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, '回复归档格式无效') from exc


def _snapshot_v2(message, question, run, workspace, calls):
    """Copy the published contract once; execution evidence is not reconstructed."""
    try:
        presentation = BusinessPresentation.model_validate(calls['presentation']).model_dump(
            mode='json', exclude={'operations'})
    except (KeyError, ValidationError) as exc:
        raise HTTPException(422, '回复缺少有效的业务展示快照') from exc
    return {
        'schema_version': 2,
        'answer': {'content': message.content},
        'presentation': presentation,
        'context': {'question_message_id': question.id, 'public_history': [], 'clarifications': [],
                    'truncated': False, 'kind': 'public_archive'},
        'resource': {'workspace_id': run.workspace_id,
                     'workspace_name': workspace.name if workspace and workspace.user_id == message.user_id else None,
                     'scope_version': run.scope_version, 'source_ids': run.resource_scope['source_ids']},
        'execution': {'run_id': run.id, 'assistant_message_id': message.id,
                      'model': run.model, 'status': run.status,
                      'created_at': utc(run.created_at), 'finished_at': utc(run.finished_at)},
        'completeness': {'missing_fields': [], 'warnings': []},
    }


async def feedback_context(db, user, session_id):
    conv = await db.scalar(select(Conversation).where(
        Conversation.id == session_id, Conversation.user_id == user.id))
    if not conv:
        raise HTTPException(404, '会话不存在')
    messages = (await db.scalars(select(Message).where(
        Message.conversation_id == session_id, Message.user_id == user.id,
        Message.role == 'assistant').order_by(Message.created_at, Message.id))).all()
    message_ids = [message.id for message in messages]
    runs = (await db.scalars(select(AgentRun).where(
        AgentRun.assistant_message_id.in_(message_ids), AgentRun.user_id == user.id,
        AgentRun.conversation_id == session_id))).all() if message_ids else []
    run_by_message = {run.assistant_message_id: run for run in runs}
    question_ids = {run.input_payload.get('user_message_id') for run in runs
                    if (run.input_payload or {}).get('user_message_id')}
    questions = (await db.scalars(select(Message).where(Message.id.in_(question_ids),
        Message.user_id == user.id, Message.conversation_id == session_id))).all() if question_ids else []
    question_by_id = {question.id: question for question in questions}
    feedback_rows = (await db.scalars(select(AnswerFeedback).where(
        AnswerFeedback.reporter_id == user.id, AnswerFeedback.assistant_message_key.in_(message_ids)))).all() if message_ids else []
    feedback_by_message = {record.assistant_message_key: record for record in feedback_rows}
    result = []
    for message in messages:
        calls = parsed(message.tool_calls, {})
        run = run_by_message.get(message.id)
        question_id = (run.input_payload or {}).get('user_message_id') if run else None
        question = question_by_id.get(question_id)
        eligible = bool(message.content.strip() and run and run.status in {'completed', 'partial'}
                        and question and question.role == 'user' and question.user_id == user.id
                        and question.conversation_id == session_id and question.scope_version == run.scope_version)
        reason = None if eligible else ('执行尚未完成' if run and run.status not in {'completed', 'partial'}
                                        else '该回复缺少可靠的原问题关联或归档')
        record = feedback_by_message.get(message.id)
        result.append({'message_id': message.id, 'run_id': run.id if run else None,
                       'run_status': run.status if run else calls.get('status'), 'eligible': eligible,
                       'ineligible_reason': reason, 'question_message_id': question.id if question else None,
                       'question_preview': question.content if question else None,
                       'feedback': summary(record) if record else None})
    return {'items': result}


async def _public_history(db, question):
    rows = (await db.scalars(select(Message).where(
        Message.user_id == question.user_id, Message.conversation_id == question.conversation_id,
        Message.scope_version == question.scope_version, Message.role.in_(['user', 'assistant']),
        Message.created_at < question.created_at).order_by(
            Message.created_at.desc(), Message.id.desc()).limit(21))).all()
    truncated = len(rows) > 20
    rows = rows[:20]
    ordered = list(reversed(rows))
    return [{'role': row.role, 'content': row.content} for row in ordered], truncated


async def create_feedback(db, user, message_id, payload):
    reporter_id, reporter_name = user.id, user.username
    message = await db.scalar(select(Message).where(Message.id == message_id, Message.user_id == reporter_id))
    if not message:
        raise HTTPException(404, '回复不存在')
    existing = await db.scalar(select(AnswerFeedback).where(
        AnswerFeedback.reporter_id == reporter_id, AnswerFeedback.assistant_message_key == message_id))
    if existing:
        return existing, False
    if message.role != 'assistant' or not message.content.strip():
        raise HTTPException(422, '只能对已有正文的助手回复提交反馈')
    run = await db.scalar(select(AgentRun).where(AgentRun.assistant_message_id == message.id,
                                                AgentRun.user_id == reporter_id))
    calls = parsed(message.tool_calls, {})
    if not isinstance(calls, dict):
        raise HTTPException(422, '历史回复格式无效，暂不支持反馈')
    if run:
        if run.status not in {'completed', 'partial'}:
            raise HTTPException(422, '请在回复完成后提交反馈')
        question = await db.get(Message, run.input_payload.get('user_message_id')) if run.input_payload.get('user_message_id') else None
        if (not question or question.role != 'user' or question.user_id != reporter_id
                or question.conversation_id != message.conversation_id or question.scope_version != message.scope_version
                or run.conversation_id != message.conversation_id or run.scope_version != message.scope_version):
            raise HTTPException(422, '该回复无法可靠关联原问题，暂不支持反馈')
    else:
        raise HTTPException(422, '该回复缺少有效执行记录，暂不支持反馈')
    conv = await db.get(Conversation, message.conversation_id)
    if not conv or conv.user_id != reporter_id:
        raise HTTPException(404, '回复不存在')
    workspace_id = run.workspace_id if run else conv.workspace_id
    workspace = await db.get(BusinessWorkspace, workspace_id) if workspace_id else None
    evidence = _snapshot_v2(message, question, run, workspace, calls)
    history, truncated = await _public_history(db, question)
    evidence['context']['public_history'] = history
    evidence['context']['truncated'] = truncated
    if run and isinstance(run.input_payload.get('resume'), list):
        evidence['context']['clarifications'] = [{'interrupt_id': item.get('interruptId'),
            'response': item.get('payload')} for item in run.input_payload['resume'] if isinstance(item, dict)]
    evidence = FeedbackSnapshotV2.model_validate(evidence).model_dump(mode='json')
    if len(json.dumps(evidence, ensure_ascii=False).encode('utf-8')) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, '回复证据超过 2MiB，反馈未提交，请联系处理人员')
    record = AnswerFeedback(reporter_id=reporter_id, reporter_name_snapshot=reporter_name,
        assistant_message_key=message.id, assistant_message_id=message.id, question_message_id=question.id,
        conversation_id=message.conversation_id, run_id=run.id if run else None, workspace_id=workspace_id,
        question_snapshot=question.content, evidence_snapshot=evidence, reason=payload.reason, user_comment=payload.comment)
    try:
        db.add(record)
        await db.flush()
        db.add(AnswerFeedbackEvent(feedback_id=record.id, version=1, action='created', actor_id=reporter_id,
                                  actor_name_snapshot=reporter_name, from_status=None, to_status='pending'))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(AnswerFeedback).where(
            AnswerFeedback.reporter_id == reporter_id, AnswerFeedback.assistant_message_key == message_id))
        if existing:
            return existing, False
        raise
    return record, True


async def get_record(db, feedback_id):
    record = await db.get(AnswerFeedback, feedback_id)
    if not record:
        raise HTTPException(404, '反馈不存在')
    return record


async def detail(db, record):
    try:
        evidence = FeedbackSnapshotV2.model_validate(record.evidence_snapshot).model_dump(mode='json')
    except ValidationError as exc:
        raise HTTPException(409, '反馈快照不符合当前数据结构') from exc
    events = (await db.scalars(select(AnswerFeedbackEvent).where(
        AnswerFeedbackEvent.feedback_id == record.id).order_by(AnswerFeedbackEvent.version))).all()
    return {**list_item(record), 'reason': record.reason, 'user_comment': record.user_comment,
            'evidence_snapshot': evidence, 'processing_note': record.processing_note,
            'last_handled_by': record.last_handled_by, 'last_handled_at': utc(record.last_handled_at),
            'original_deleted': record.assistant_message_id is None,
            'history': [dict(version=e.version, action=e.action, actor_id=e.actor_id,
                             actor_name=e.actor_name_snapshot, from_status=e.from_status, to_status=e.to_status,
                             old_note=e.old_note, new_note=e.new_note, created_at=utc(e.created_at)) for e in events]}


async def update_feedback(db, user, record, payload):
    if record.version != payload.expected_version:
        raise HTTPException(409, '记录已被其他处理人更新，请重新加载后处理')
    if record.status == 'resolved' and payload.status == 'pending' and (
            not payload.processing_note or payload.processing_note == record.processing_note):
        raise HTTPException(422, '重新打开时请填写新的原因说明')
    # Even a no-op must verify the current version against the database.
    changed = record.status != payload.status or record.processing_note != payload.processing_note
    now = datetime.utcnow()
    old_status, old_note = record.status, record.processing_note
    values = dict(status=payload.status, processing_note=payload.processing_note,
                  version=record.version + 1, last_handled_by=user.id, last_handled_at=now, updated_at=now) if changed else {'version': record.version}
    result = await db.execute(update(AnswerFeedback).where(
        AnswerFeedback.id == record.id, AnswerFeedback.version == payload.expected_version).values(**values),
        execution_options={'synchronize_session': False})
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, '记录已被其他处理人更新，请重新加载后处理')
    if changed:
        db.add(AnswerFeedbackEvent(feedback_id=record.id, version=payload.expected_version + 1,
            action='reopened' if old_status == 'resolved' and payload.status == 'pending' else 'updated',
            actor_id=user.id, actor_name_snapshot=user.username, from_status=old_status, to_status=payload.status,
            old_note=old_note, new_note=payload.processing_note, created_at=now))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(record)
    return await detail(db, record)
