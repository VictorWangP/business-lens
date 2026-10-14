import asyncio
import json
import logging
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from opentelemetry import trace
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation, Message
from app.models.platform import AgentRun, RunEvent
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.agents.executor import AgentExecutor
from app.agents.answer import history_text, requests_code, AnswerValidationError
from app.analytics.presentation import json_value

logger = logging.getLogger(__name__)


async def prepare_chat(db, user_id, payload):
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
            AgentRun.status.in_(['queued', 'running', 'cancel_requested'])).limit(1))
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
        conv = Conversation(user_id=user_id, title=payload.query[:40], model=cfg['model_id'], workspace_id=workspace.id)
        db.add(conv)
        await db.flush()
    elif payload.model:
        conv.model = cfg['model_id']
    conv.scope_version = workspace.version
    conv.kb_ids, conv.source_ids = json.dumps(kb_ids), json.dumps(source_ids)
    conv.updated_at = datetime.utcnow()
    recent = (await db.scalars(select(Message).where(
        Message.conversation_id == conv.id, Message.user_id == user_id,
        Message.scope_version == workspace.version)
        .order_by(Message.created_at.desc()).limit(12))).all()
    history = [{'role': m.role, 'content': m.content} for m in reversed(recent)
               if m.role in {'user', 'assistant'} and m.content]
    preceding_query = ''
    for item in history:
        if item['role'] == 'user':
            preceding_query = item['content']
        else:
            item['content'] = history_text(item['content'], requests_code(preceding_query))
    total, selected = 0, []
    for item in reversed(history):
        if total + len(item['content']) > 24000:
            break
        total += len(item['content'])
        selected.insert(0, item)
    memory = await MemoryService.get_user_memory_context(db, user_id, include_facts=False)

    user_message = Message(user_id=user_id, conversation_id=conv.id, scope_version=workspace.version,
                          role='user', content=payload.query)
    db.add(user_message)
    await db.flush()
    from app.services.frequent_service import enqueue
    await enqueue(db, user_message, kb_ids or [], source_ids or [])

    run = AgentRun(user_id=user_id, conversation_id=conv.id, model=cfg['model_id'], workspace_id=workspace.id,
                   scope_version=workspace.version,
                   resource_scope={'kb_ids': kb_ids, 'source_ids': source_ids},
                   input_payload={'query': payload.query, 'history': selected, 'memory': memory,
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
    await persist_run_event(run_id, {'type': 'status', 'status': 'running'})
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
        await persist_run_event(run_id, {'type': 'error', 'message': str(exc) if isinstance(exc, ValueError) else '模型配置不可用'})
        await persist_run_event(run_id, {'type': 'done', 'status': 'failed'})
        return

    executor = AgentExecutor(user_id, resource_scope.get('kb_ids', []), resource_scope.get('source_ids', []), cfg, enable_suggestions=enable_suggestions)

    async def run_agent():
        status = 'completed'
        suggestions = []
        try:
            async for event in executor.stream(payload['query'], payload.get('history', []), payload.get('memory', '')):
                if event.get('type') == 'suggestions':
                    suggestions = event.get('items', [])
                elif event.get('type') == 'answer':
                    suggestions = event['answer']['suggestions']
                await persist_run_event(run_id, event)
            if executor.errors:
                status = 'partial'
        except asyncio.CancelledError:
            async with AsyncSessionLocal() as db:
                current = await db.get(AgentRun, run_id)
                status = 'cancelled' if current and current.status == 'cancel_requested' else 'failed'
            if status == 'failed':
                await persist_run_event(run_id, {'type': 'error', 'message': '执行进程停止，请重新发起任务'})
        except Exception as exc:
            status = 'failed'
            logger.warning('Agent run failed: run=%s category=%s', run_id, type(exc).__name__)
            await persist_run_event(run_id, {'type': 'error', 'message': '回答格式校验失败，请重新提问。' if isinstance(exc, AnswerValidationError) else '执行失败，请检查模型、数据源或执行预算。'})
        finally:
            done_payload = {'type': 'done', 'status': status}
            if status == 'completed' and suggestions:
                done_payload['suggestions'] = suggestions
            await asyncio.shield(persist_run_event(run_id, done_payload))
            if status == 'completed':
                try:
                    async with AsyncSessionLocal() as db:
                        run = await db.get(AgentRun, run_id)
                        if run:
                            query = payload['query']
                            message = await db.get(Message, assistant_message_id) if assistant_message_id else None
                            if message and message.content:
                                await MemoryService.extract_and_save_memory(db, user_id, run.conversation_id, query, message.content)
                except Exception as exc:
                    logger.warning('Memory extraction failed: run=%s category=%s', run_id, type(exc).__name__)

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
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
        if not run:
            return None
        last = await db.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)) or 0
        sequence = last + 1
        span_context = trace.get_current_span().get_span_context()
        trace_id = format(span_context.trace_id, '032x') if span_context.is_valid else ''
        payload = json_value({**event, 'run_id': run_id, 'sequence': sequence, 'trace_id': trace_id})
        db.add(RunEvent(run_id=run_id, sequence=sequence, event_type=event.get('type', 'event'), payload=payload))

        message = await db.get(Message, run.assistant_message_id) if run.assistant_message_id else None
        calls = json.loads(message.tool_calls or '{}') if message and message.tool_calls else {}
        kind = event.get('type')
        if message:
            if kind in {'tool_start', 'tool_end'}:
                calls.setdefault('execution_events', []).append({key: event[key] for key in ('type', 'name') if key in event})
            elif kind == 'query_result':
                calls.setdefault('query_results', []).append(event)
            elif kind == 'chunk':
                message.content += event.get('content', '')
            elif kind == 'answer':
                message.content = event['content']
                calls['answer'] = event['answer']
                calls.pop('suggestions', None)
            elif kind == 'tool_call':
                calls['metrics'], calls['chart'] = event.get('metrics'), event.get('chart')
            elif kind == 'citations':
                message.citations = json.dumps(event.get('items', []), ensure_ascii=False)
            elif kind == 'error':
                message.content = (message.content + '\n' if message.content else '') + event.get('message', '执行失败')
            elif kind == 'status':
                calls['status'] = event.get('status', 'running')
            elif kind == 'suggestions':
                calls['suggestions'] = event.get('items', [])
            elif kind == 'done':
                calls['status'] = event.get('status', 'failed')
                if event.get('suggestions') and 'answer' not in calls:
                    calls['suggestions'] = event['suggestions']
                run.status = calls['status']
                run.error = event.get('message', '')
                run.finished_at = datetime.utcnow()
                run.lease_expires_at = None
                conversation = await db.get(Conversation, run.conversation_id)
                if conversation:
                    conversation.updated_at = datetime.utcnow()
            calls['run_id'] = run_id
            calls['last_sequence'] = sequence
            message.tool_calls = json.dumps(calls, ensure_ascii=False)
        if run.status in {'running', 'cancel_requested'}:
            run.lease_expires_at = datetime.utcnow() + timedelta(seconds=settings.AGENT_TIMEOUT + 90)
        await db.commit()
        return payload


async def stream_run_events(run_id: str, after_sequence: int = 0, initial: dict | None = None):
    cursor = max(0, after_sequence)
    if initial:
        yield 'data: ' + json.dumps(initial, ensure_ascii=False) + '\n\n'
    while True:
        async with AsyncSessionLocal() as db:
            rows = (await db.scalars(select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.sequence > cursor
            ).order_by(RunEvent.sequence).limit(200))).all()
            run = await db.get(AgentRun, run_id)
            state = run.status if run else 'failed'
        for row in rows:
            cursor = row.sequence
            yield 'data: ' + json.dumps(row.payload, ensure_ascii=False) + '\n\n'
        if state in {'completed', 'partial', 'failed', 'cancelled'} and not rows:
            break
        if not rows:
            yield ': keep-alive\n\n'
            await asyncio.sleep(0.5)


