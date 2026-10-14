import asyncio
import json
import logging
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation, Message
from app.models.platform import AgentRun, RunEvent
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.agents.executor import AgentExecutor
from app.agents.answer import AnswerValidationError
from ag_ui.core import Event
from ag_ui.encoder import EventEncoder
from pydantic import TypeAdapter
from app.analytics.presentation import json_value

logger = logging.getLogger(__name__)


async def prepare_chat(db, user_id, payload, *, thread_id=None, run_id=None, user_message_id=None):
    from app.services.resource_scope import get_workspace, validate_scope

    existing = None
    if payload.conversation_id:
        existing = await db.scalar(select(Conversation).where(
            Conversation.id == payload.conversation_id, Conversation.user_id == user_id))
        if not existing:
            raise HTTPException(404, '会话不存在')
        if payload.workspace_id and payload.workspace_id != existing.workspace_id:
            raise HTTPException(422, '已有会话不能更换业务空间，请新建对话')
        active = await db.scalar(select(AgentRun.id).where(
            AgentRun.conversation_id == existing.id,
            AgentRun.status.in_(['queued', 'running', 'cancel_requested', 'paused'])).limit(1))
        if active:
            raise HTTPException(409, '当前会话仍有问题正在处理，请等待完成或停止后再提问')

    workspace_id = existing.workspace_id if existing else payload.workspace_id
    if not workspace_id:
        raise HTTPException(422, '请先选择业务空间')
    workspace = await get_workspace(db, user_id, workspace_id)
    kb_ids, source_ids = json.loads(workspace.kb_ids), json.loads(workspace.source_ids)
    await validate_scope(db, user_id, kb_ids, source_ids)
    if not kb_ids and not source_ids:
        raise HTTPException(422, '当前业务空间尚未关联来源，请前往业务空间管理页配置后继续提问')
    try:
        cfg = await LLMService.get_model_config(db, user_id, payload.model)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    conv = existing
    if conv is None:
        conv = Conversation(**({'id': thread_id} if thread_id else {}), user_id=user_id, title=payload.query[:40], model=cfg['model_id'], workspace_id=workspace.id)
        db.add(conv)
        await db.flush()
    elif payload.model:
        conv.model = cfg['model_id']
    conv.scope_version = workspace.version
    conv.kb_ids, conv.source_ids = json.dumps(kb_ids), json.dumps(source_ids)
    conv.updated_at = datetime.utcnow()
    # Model history belongs to LangGraph checkpoints. The complete chat archive is
    # retained independently and is never clipped to a fixed message/character count.
    memory = await MemoryService.get_user_memory_context(db, user_id, include_facts=False)

    user_message = Message(**({'id': user_message_id} if user_message_id else {}), user_id=user_id, conversation_id=conv.id, scope_version=workspace.version,
                          role='user', content=payload.query)
    db.add(user_message)
    await db.flush()
    from app.services.frequent_service import enqueue
    await enqueue(db, user_message, kb_ids or [], source_ids or [])

    run = AgentRun(**({'id': run_id} if run_id else {}), user_id=user_id, conversation_id=conv.id, model=cfg['model_id'], workspace_id=workspace.id,
                   scope_version=workspace.version,
                   resource_scope={'kb_ids': kb_ids, 'source_ids': source_ids},
                   input_payload={'query': payload.query, 'memory': memory,
                                  'user_message_id': user_message.id})
    db.add(run)
    await db.flush()
    assistant_message = Message(
        user_id=user_id, conversation_id=conv.id, scope_version=workspace.version,
        role='assistant', content='',
        tool_calls=json.dumps({'run_id': run.id, 'status': 'queued', 'last_sequence': 0}, ensure_ascii=False),
    )
    db.add(assistant_message)
    await db.flush()
    run.assistant_message_id = assistant_message.id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, '当前会话已有 Agent 任务正在处理，请等待完成或停止后再提问') from exc
    await db.refresh(run)
    return run


async def claim_agent_run(run_id: str) -> bool:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(update(AgentRun).where(
            AgentRun.id == run_id, AgentRun.status == 'queued'
        ).values(status='running', attempts=AgentRun.attempts + 1,
                 lease_expires_at=now + timedelta(seconds=settings.AGENT_TIMEOUT + 90)))
        await db.commit()
        return result.rowcount == 1


async def execute_agent_run(run_id: str):
    """Execute one durable AgentRun. The caller owns worker process lifecycle, not an HTTP request."""
    if not await claim_agent_run(run_id):
        return

    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
        if not run:
            return
        user_id, model_id = run.user_id, run.model
        resource_scope, payload = dict(run.resource_scope or {}), dict(run.input_payload or {})
        assistant_message_id = run.assistant_message_id

    try:
        async with AsyncSessionLocal() as db:
            cfg = await LLMService.get_model_config(db, user_id, model_id)
            from app.models.config import AppConfig
            nq = await db.scalar(select(AppConfig).where(AppConfig.user_id == user_id, AppConfig.config_key == 'next_questions'))
            enable_suggestions = nq.is_enabled if nq else True
    except Exception as exc:
        await persist_run_event(run_id, {'type': 'RUN_ERROR', 'message': str(exc) if isinstance(exc, ValueError) else '模型配置不可用'})

        return

    executor = AgentExecutor(user_id, resource_scope.get('kb_ids', []), resource_scope.get('source_ids', []), cfg, enable_suggestions=enable_suggestions)

    async def run_agent():
        try:
            # Restore exact evidence when a worker resumes from its checkpoint.
            async with AsyncSessionLocal() as db:
                current = await db.get(AgentRun, run_id)
                saved = await db.get(Message, assistant_message_id)
                metadata = json.loads(saved.tool_calls or '{}') if saved else {}
                executor.queries = metadata.get('query_results', [])
                executor.citations = {item['id']: item for item in json.loads(saved.citations or '[]')} if saved else {}
                executor.citation_ids = {item.get('chunk_id', item['id']): item['id'] for item in executor.citations.values()}
                checkpoint_thread = f'{user_id}:{current.conversation_id}:{current.scope_version}'
                recover = current.attempts > 1 and not payload.get('resume')
            delivery = []
            async for event in executor.stream(payload['query'], memory=payload.get('memory', ''),
                thread_id=checkpoint_thread, run_id=run_id,
                user_message_id=payload['user_message_id'], assistant_message_id=assistant_message_id,
                resume=payload.get('resume'), recover=recover, known_tool_calls=[item['tool_id'] for item in metadata.get('execution_events', []) if item['type']=='tool_start']):
                # Wire thread IDs remain application conversation IDs; checkpoint namespaces are private.
                if event['type'] in {'RUN_STARTED', 'RUN_FINISHED'}:
                    event['threadId'] = current.conversation_id
                if event['type'] in {'TEXT_MESSAGE_START','TEXT_MESSAGE_CONTENT','TEXT_MESSAGE_END','ACTIVITY_SNAPSHOT'}:
                    delivery.append(event)
                elif event['type'] == 'RUN_FINISHED' and delivery:
                    await persist_run_events(run_id, [*delivery, event])
                    delivery.clear()
                    try:
                        async with AsyncSessionLocal() as db:
                            await MemoryService.extract_and_save_memory(db, user_id, current.conversation_id, payload['query'], '')
                    except Exception as exc:
                        logger.warning('Preference extraction failed: category=%s', type(exc).__name__)
                else:
                    await persist_run_event(run_id, event)
        except asyncio.CancelledError:
            async with AsyncSessionLocal() as db:
                current = await db.get(AgentRun, run_id)
                explicitly_cancelled = current and current.status == 'cancel_requested'
                if current and not explicitly_cancelled:
                    # Worker shutdown is resumable; HTTP disconnection never reaches here.
                    current.status = 'queued'
                    current.lease_expires_at = None
                    await db.commit()
            if explicitly_cancelled:
                await asyncio.shield(persist_run_event(run_id, {'type': 'RUN_ERROR', 'code': 'CANCELLED', 'message': '用户已停止执行'}))
            raise
        except Exception as exc:
            logger.warning('Agent run failed: run=%s category=%s reason=%s', run_id, type(exc).__name__, str(exc) if isinstance(exc, AnswerValidationError) else '')
            await persist_run_event(run_id, {'type': 'RUN_ERROR', 'message':
                '回答格式校验失败，请重新提问。' if isinstance(exc, AnswerValidationError) else '执行失败，请检查模型、数据源或执行预算。'})

    async def monitor_cancel(task):
        while not task.done():
            await asyncio.sleep(0.5)
            async with AsyncSessionLocal() as db:
                run = await db.get(AgentRun, run_id)
                if not run:
                    task.cancel()
                    return
                if run.status == 'cancel_requested':
                    task.cancel()
                    return
                if run.status == 'running':
                    run.lease_expires_at = datetime.utcnow() + timedelta(seconds=settings.AGENT_TIMEOUT + 90)
                    await db.commit()

    agent_task = asyncio.create_task(run_agent())
    monitor_task = asyncio.create_task(monitor_cancel(agent_task))
    try:
        await agent_task
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)


async def persist_run_event(run_id: str, event: dict):
    results = await persist_run_events(run_id, [event])
    return results[0] if results else None


async def persist_run_events(run_id: str, events: list[dict]):
    """Final text, data and terminal status commit together; replay never sees half an answer."""
    async with AsyncSessionLocal() as db:
        run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not run:
            return []
        results = []
        offset = (run.input_payload or {}).get('event_offset', 0)
        if events and events[0]['type']=='RUN_ERROR' and not await db.scalar(select(RunEvent.id).where(
            RunEvent.run_id==run_id, RunEvent.sequence>offset, RunEvent.event_type=='RUN_STARTED').limit(1)):
            await _append_event(db, run, {'type':'RUN_STARTED','threadId':run.conversation_id,'runId':run.id})
            await db.flush()
        for event in events:
            payload = await _append_event(db, run, event)
            if payload:
                results.append(payload)
            await db.flush()
        await db.commit()
        return results


async def _append_event(db, run, event):
    run_id = run.id
    last = await db.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)) or 0
    offset = (run.input_payload or {}).get('event_offset', 0)
    if event['type'] == 'RUN_STARTED' and await db.scalar(select(RunEvent.id).where(RunEvent.run_id == run_id, RunEvent.sequence > offset, RunEvent.event_type == 'RUN_STARTED').limit(1)):
        return None
    sequence = last + 1
    payload = json_value(event)
    payload['sequence'] = sequence
    db.add(RunEvent(run_id=run_id, sequence=sequence, event_type=event.get('type', 'CUSTOM'), payload=payload))
    message = await db.get(Message, run.assistant_message_id) if run.assistant_message_id else None
    calls = json.loads(message.tool_calls or '{}') if message else {}
    kind = event.get('type')
    if message:
        if kind in {'TOOL_CALL_START', 'TOOL_CALL_RESULT'}:
            calls.setdefault('execution_events', []).append({
                'type': 'tool_start' if kind == 'TOOL_CALL_START' else 'tool_end',
                'name': event.get('toolCallName') or next((item.get('name','') for item in calls.get('execution_events', []) if item.get('tool_id') == event['toolCallId']), ''), 'tool_id': event['toolCallId']})
        elif kind == 'CUSTOM' and event.get('name') == 'business.evidence':
            evidence = event['value']
            if evidence['type'] == 'query_result':
                calls.setdefault('query_results', []).append(evidence)
            elif evidence['type'] == 'citations':
                message.citations = json.dumps(evidence['items'], ensure_ascii=False)
        elif kind == 'TEXT_MESSAGE_CONTENT':
            message.content = event['delta']
        elif kind == 'ACTIVITY_SNAPSHOT' and event.get('activityType') == 'business-answer':
            event['content']['operations'] = calls.get('execution_events', [])
            calls['presentation'] = event['content']
            payload['content'] = event['content']
            calls['answer'] = event['content']['answer']
        elif kind == 'RUN_ERROR':
            message.content = message.content or event.get('message', '执行失败')
            run.status = 'cancelled' if event.get('code') == 'CANCELLED' else 'failed'
            run.error = event.get('message', '')
        elif kind == 'RUN_FINISHED':
            run.status = 'paused' if event.get('outcome', {}).get('type') == 'interrupt' else 'completed'
            calls['interrupts'] = event.get('outcome', {}).get('interrupts', [])
        if kind in {'RUN_ERROR', 'RUN_FINISHED'}:
            calls['status'] = run.status
            run.finished_at = datetime.utcnow() if run.status != 'paused' else None
            run.lease_expires_at = None
            conversation = await db.get(Conversation, run.conversation_id)
            if conversation:
                conversation.updated_at = datetime.utcnow()
        calls['run_id'] = run_id
        calls['last_sequence'] = sequence
        message.tool_calls = json.dumps(calls, ensure_ascii=False)
    if run.status in {'running', 'cancel_requested'}:
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=settings.AGENT_TIMEOUT + 90)
    return payload


async def stream_run_events(run_id: str, after_sequence: int = 0, initial: dict | None = None, public_run_id: str | None = None):
    """Replay durable standard events with the official protocol encoder."""
    encoder, validator = EventEncoder(), TypeAdapter(Event)
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
        offset = (run.input_payload or {}).get('event_offset', 0) if run else 0
    cursor = max(0, after_sequence, offset)
    visible_calls = set()
    if initial:
        yield encoder.encode(validator.validate_python(initial))
    while True:
        async with AsyncSessionLocal() as db:
            rows = (await db.scalars(select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.sequence > cursor
            ).order_by(RunEvent.sequence).limit(200))).all()
            run = await db.get(AgentRun, run_id)
            state = run.status if run else 'failed'
        for row in rows:
            cursor = row.sequence
            # Exact result evidence is private to the worker and authorized result APIs.
            if row.event_type == 'CUSTOM' and row.payload.get('name') == 'business.evidence':
                continue
            if row.event_type == 'TOOL_CALL_START':
                visible_calls.add(row.payload['toolCallId'])
            if row.event_type in {'TOOL_CALL_ARGS','TOOL_CALL_END','TOOL_CALL_RESULT'} and row.payload['toolCallId'] not in visible_calls:
                continue
            payload = dict(row.payload)
            if public_run_id and row.event_type in {'RUN_STARTED','RUN_FINISHED'}:
                payload['runId'] = public_run_id
            yield encoder.encode(validator.validate_python(payload))
        if state in {'completed', 'partial', 'failed', 'cancelled', 'paused'} and not rows:
            break
        if not rows:
            yield ': keep-alive\n\n'
            await asyncio.sleep(0.5)
