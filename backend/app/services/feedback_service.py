import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models.conversation import Conversation, Message, BusinessWorkspace
from app.models.platform import AgentRun
from app.models.feedback import AnswerFeedback, AnswerFeedbackEvent

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


def pick(value, keys):
    return {key: value[key] for key in keys if key in value} if isinstance(value, dict) else {}


def parsed(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(422, '历史回复格式无效，暂不支持反馈')


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
                or run.conversation_id != message.conversation_id):
            raise HTTPException(422, '该回复无法可靠关联原问题，暂不支持反馈')
    else:
        if calls.get('run_id') or calls.get('status') not in {None, 'completed', 'partial'}:
            raise HTTPException(422, '该回复缺少有效执行记录，暂不支持反馈')
        # Equal timestamps cannot prove which question preceded the assistant answer.
        candidates = (await db.scalars(select(Message).where(
            Message.conversation_id == message.conversation_id, Message.user_id == reporter_id,
            Message.scope_version == message.scope_version, Message.role == 'user',
            Message.created_at <= message.created_at).order_by(Message.created_at.desc()).limit(2))).all()
        if (not candidates or candidates[0].created_at == message.created_at or
                len(candidates) > 1 and candidates[0].created_at == candidates[1].created_at):
            raise HTTPException(422, '该历史回复无法可靠关联原问题，暂不支持反馈')
        question = candidates[0]
    conv = await db.get(Conversation, message.conversation_id)
    if not conv or conv.user_id != reporter_id:
        raise HTTPException(404, '回复不存在')
    workspace_id = run.workspace_id if run else conv.workspace_id
    workspace = await db.get(BusinessWorkspace, workspace_id) if workspace_id else None
    answer = {'content': message.content}
    raw_structured = calls.get('answer') if isinstance(calls.get('answer'), dict) else {}
    structured = pick(raw_structured, ('version', 'suggestions'))
    structured['sections'] = []
    for section in raw_structured.get('sections', []):
        clean = pick(section, ('title', 'summary', 'query_id', 'show_table'))
        if isinstance(section, dict) and section.get('code'):
            clean['code'] = pick(section['code'], ('language', 'content'))
        structured['sections'].append(clean)
    answer['structured'] = structured
    answer['metrics'] = [pick(m, ('label', 'value', 'change', 'trend')) for m in (calls.get('metrics') or [])]
    answer['chart'] = pick(calls.get('chart'), ('type', 'title', 'x_key', 'y_keys', 'data')) or None
    answer['citations'] = [pick(c, ('id', 'doc_id', 'doc_name', 'chunk_index', 'content', 'score', 'chunk_id', 'version', 'pages', 'headings', 'retrieval_warning'))
                           for c in parsed(message.citations, [])]
    queries = [pick(q, ('query_id', 'citation_id', 'source_name', 'retrieved_at', 'rows', 'truncated', 'sql', 'parameters'))
               for q in (calls.get('query_results') or [])]
    evidence = {
        'schema_version': 1, 'answer': answer,
        'context': {'question_message_id': question.id, 'history': [pick(h, ('role', 'content'))
                    for h in (run.input_payload.get('history', []) if run else [])]},
        'resource': {'workspace_id': workspace_id, 'workspace_name': workspace.name if workspace and workspace.user_id == reporter_id else None,
                     'scope_version': message.scope_version,
                     **pick(run.resource_scope if run else {'kb_ids': parsed(conv.kb_ids, []), 'source_ids': parsed(conv.source_ids, [])}, ('kb_ids', 'source_ids'))},
        'execution': {'model': run.model if run else conv.model, 'status': run.status if run else calls.get('status', 'completed'),
                      'created_at': utc(run.created_at if run else message.created_at),
                      'finished_at': utc(run.finished_at) if run else None, 'queries': queries},
    }
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
    events = (await db.scalars(select(AnswerFeedbackEvent).where(
        AnswerFeedbackEvent.feedback_id == record.id).order_by(AnswerFeedbackEvent.version))).all()
    return {**list_item(record), 'reason': record.reason, 'user_comment': record.user_comment,
            'evidence_snapshot': record.evidence_snapshot, 'processing_note': record.processing_note,
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
