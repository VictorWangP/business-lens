"""Context boundaries, exact evidence paging, budget diagnostics and durable recovery."""
import json
import uuid
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.budget import TokenBudget, BudgetExceeded
from app.agents.context import bounded_result, result_page, serialized_tokens, ContextManagement
from app.agents.executor import AgentExecutor
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.platform import AgentRun, RunEvent
from app.agents.evidence import tool_result
from app.application.chat import persist_run_event
from agent_helpers import CFG, answer, install_model, ScriptedModel, presentation


def test_budget_reports_context_and_total_separately_without_content(caplog):
    caplog.set_level('INFO')
    secret = 'private-business-question'
    context = TokenBudget(100000, 20, output=10, run_id='context-run')
    with pytest.raises(BudgetExceeded) as error:
        context.on_chat_model_start({}, [[HumanMessage(content=secret)]], invocation_params={'tools': []})
    assert error.value.code == 'CONTEXT_TOKEN_LIMIT'
    total = TokenBudget(1000, 10000, output=10, run_id='total-run')
    total.spent = 999
    with pytest.raises(BudgetExceeded) as error:
        total.on_chat_model_start({}, [[HumanMessage(content=secret)]], invocation_params={'tools': []})
    assert error.value.code == 'TOTAL_TOKEN_LIMIT'
    assert 'message_tokens=' in caplog.text and 'output_reserved=' in caplog.text
    assert secret not in caplog.text


def test_budget_uses_provider_usage_and_estimated_fallback(caplog):
    caplog.set_level('INFO')
    budget = TokenBudget(10000, 10000, output=10)
    budget.on_chat_model_start({}, [[HumanMessage(content='hello')]], run_id='first')
    message = AIMessage(content='done', usage_metadata={'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120})
    budget.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id='first')
    assert budget.spent == 120
    budget.on_chat_model_start({}, [[HumanMessage(content='hello')]], run_id='second')
    budget.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content='done'))]]), run_id='second')
    assert budget.spent > 120
    assert 'usage_source=provider' in caplog.text and 'usage_source=estimated' in caplog.text


def test_large_tool_preview_is_bounded_valid_json_and_does_not_mutate_artifact():
    value = {'citation_id': 'Qexact', 'rows': [{'金额': '123456.7800', '说明': '重要原文'*8000}], 'truncated': False}
    original = deepcopy(value)
    preview = bounded_result(value, 'Tresult', 256)
    assert serialized_tokens(preview) <= 256
    assert preview['tool_result_id'] == 'Tresult'
    assert preview['tool_output_truncated'] is True
    assert value == original
    assert json.loads(json.dumps(preview, ensure_ascii=False)) == preview


def test_large_tool_result_pages_roundtrip_unicode_and_exact_decimals():
    value = {'rows': [{'金额': '0.300000000000000001', '原文': '中文🙂引用'*500}]}
    offset, parts = 0, []
    while offset is not None:
        page = result_page(value, 'Tresult', offset, 256)
        assert serialized_tokens(page) <= 256
        parts.append(page['content'])
        following = page['next_offset']
        assert following is None or following > offset
        offset = following
    assert json.loads(''.join(parts)) == value
    with pytest.raises(ValueError):
        result_page(value, 'Tresult', -1, 256)


async def stream(executor, thread, query='查看业务', **kwargs):
    return [event async for event in executor.stream(query, thread_id=thread,
        run_id=kwargs.pop('run_id', str(uuid.uuid4())), user_message_id=kwargs.pop('user_message_id', str(uuid.uuid4())),
        assistant_message_id=str(uuid.uuid4()), **kwargs)]


@pytest.mark.asyncio
async def test_new_turn_preserves_execution_prefix_without_publishing_drafts(monkeypatch):
    seen = []
    def respond(messages):
        seen.append(messages)
        if len(seen) == 1:
            return AIMessage(content='内部草稿不得进入下一轮', tool_calls=[{'id': 'r', 'name': 'list_available_resources', 'args': {}}])
        return answer('按2026年1月华东口径分析。')
    install_model(monkeypatch, respond)
    thread = str(uuid.uuid4())
    first = await stream(AgentExecutor('u', [], CFG), thread, '查询2026年1月华东')
    assert first[-1]['type'] == 'RUN_FINISHED'
    second = await stream(AgentExecutor('u', [], CFG), thread, '沿用刚才条件')
    assert second[-1]['type'] == 'RUN_FINISHED'
    latest = seen[-1]
    assert any(isinstance(message, ToolMessage) for message in latest)
    assert latest[:len(seen[1])] == seen[1]
    assert any('2026年1月华东' in str(message.content) for message in latest)
    assert '内部草稿' not in json.dumps(first, ensure_ascii=False)
    # Execution messages still exist in old checkpoints; only next-run model history changes.
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        checkpoints = [state async for state in saver.alist({'configurable': {'thread_id': thread}})]
        assert any(any(getattr(message, 'type', '') == 'tool' for message in state.checkpoint['channel_values'].get('messages', [])) for state in checkpoints)


@pytest.mark.asyncio
async def test_identical_tools_block_after_two_calls_and_reset_next_turn(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_IDENTICAL_TOOL_CALLS', 2)
    def respond(messages):
        current = next(i for i in range(len(messages)-1, -1, -1) if isinstance(messages[i], HumanMessage))
        count = sum(isinstance(message, ToolMessage) and message.name == 'list_available_resources' for message in messages[current:])
        if count < 3:
            return AIMessage(content='', tool_calls=[{'id': f'r{count}', 'name': 'list_available_resources', 'args': {}}])
        assert 'REPEATED_TOOL_CALL' in messages[-1].content
        return answer()
    install_model(monkeypatch, respond)
    thread = str(uuid.uuid4())
    for _ in range(2):
        executor = AgentExecutor('u', [], CFG)
        events = await stream(executor, thread)
        assert executor.sql.calls == 2
        assert events[-1]['type'] == 'RUN_FINISHED'


@pytest.mark.asyncio
async def test_large_tool_results_have_durable_authorized_readback(monkeypatch):
    from test_frequent import seed
    user, other, conversation, _, _ = await seed()
    async with AsyncSessionLocal() as db:
        run = AgentRun(user_id=user, conversation_id=conversation, model='test', scope_version=1, status='running')
        db.add(run)
        await db.commit()
        run_id = run.id
    monkeypatch.setattr(settings, 'AGENT_TOOL_OUTPUT_TOKENS', 256)
    full = {'columns': [{'name': f'column{i}', 'description': '很长的业务说明'*100} for i in range(50)]}
    async def schema() -> dict:
        """Read a large authorized schema."""
        return full
    executor = AgentExecutor(user, [], CFG)
    result = await executor.sql.tool(schema).ainvoke({'type': 'tool_call', 'id': 'large', 'name': 'schema', 'args': {}})
    preview = json.loads(result.content)
    reference = preview['tool_result_id']
    event = executor.sql.pending.get_nowait()
    await persist_run_event(run_id, {'type': 'CUSTOM', 'name': 'business.evidence', 'value': event})
    assert await tool_result(user, conversation, 1, reference) == full
    for owner, conv, scope in [(other, conversation, 1), (user, conversation, 2), (user, 'other-conversation', 1)]:
        with pytest.raises(ValueError):
            await tool_result(owner, conv, scope, reference)


@pytest.mark.asyncio
async def test_budget_failure_survives_adapter_and_is_archived_with_code(monkeypatch):
    from test_platform import seed
    from app.services.llm_service import LLMService
    from app.models.conversation import BusinessWorkspace, Message
    from app.schemas.chat import ChatRequest
    from app.application.chat import prepare_chat, execute_agent_run
    from sqlalchemy import select
    user, _ = await seed()
    async with AsyncSessionLocal() as db:
        from app.models.platform import DataSource
        source = DataSource(user_id=user, name='预算测试源', connection_secret='unused')
        db.add(source); await db.flush()
        ws = BusinessWorkspace(user_id=user, name='预算测试', source_ids=json.dumps([source.id]))
        db.add(ws)
        await db.commit()
        workspace_id = ws.id
    async def config(*args, **kwargs):
        return CFG
    monkeypatch.setattr(LLMService, 'get_model_config', config)
    monkeypatch.setattr(settings, 'AGENT_MAX_TOTAL_TOKENS', 1)
    def model(**kwargs):
        return ScriptedModel(respond=lambda messages: answer(), callbacks=kwargs['callbacks'])
    monkeypatch.setattr('langchain_openai.ChatOpenAI', model)
    async with AsyncSessionLocal() as db:
        run = await prepare_chat(db, user, ChatRequest(query='查询收入', workspace_id=workspace_id))
        rid = run.id
    await execute_agent_run(rid)
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, rid)
        assert run.status == 'failed'
        event = await db.scalar(select(RunEvent).where(RunEvent.run_id == rid, RunEvent.event_type == 'RUN_ERROR'))
        assert event.payload['code'] == 'TOTAL_TOKEN_LIMIT'
        assert '累计' in event.payload['message']
        saved = await db.get(Message, run.assistant_message_id)
        assert '累计' in saved.content


@pytest.mark.asyncio
async def test_budget_and_repeat_counts_resume_from_checkpoint(monkeypatch):
    # Stop at a tool boundary, then restore a fresh executor/model with the same budget.
    thread, run_id = str(uuid.uuid4()), 'durable-budget'
    monkeypatch.setattr(settings, 'AGENT_MAX_TOTAL_TOKENS', 5000)
    def model(**kwargs):
        return ScriptedModel(respond=lambda messages: answer(), callbacks=kwargs['callbacks'])
    monkeypatch.setattr('langchain_openai.ChatOpenAI', model)
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph = AgentExecutor('u', [], CFG).build_graph(saver)
        await graph.aupdate_state({'configurable': {'thread_id': thread}}, {
            'messages': [HumanMessage(id='original', content='分析业务'), AIMessage(content='', tool_calls=[
                {'id': 'resources', 'name': 'list_available_resources', 'args': {}}])],
            'budget_spent': 4999, 'budget_run_id': run_id,
            'budget_accounted_message_id': 'accounted'}, as_node='model')
    executor = AgentExecutor('u', [], CFG)
    with pytest.raises(BudgetExceeded) as error:
        await stream(executor, thread, recover=True, run_id=run_id, user_message_id='original')
    assert error.value.code == 'TOTAL_TOKEN_LIMIT'
    assert executor.budget.spent >= 4999


@pytest.mark.asyncio
async def test_old_tool_bodies_prune_before_summary_and_keep_pairs(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_SUMMARY_TRIGGER_TOKENS', 2000)
    monkeypatch.setattr(settings, 'AGENT_RECENT_TOOL_RESULTS', 1)
    model = ScriptedModel(respond=lambda messages: pytest.fail('Pruning should avoid a summary call'))
    middleware = ContextManagement(model, TokenBudget(64000, 32768), system_tokens=100, schema_tokens=100)
    messages = [HumanMessage(content='查询销售'),
        AIMessage(content='', tool_calls=[{'id': 'old', 'name': 'get_business_schema', 'args': {}}]),
        ToolMessage(content='旧字段说明'*3000, tool_call_id='old', name='get_business_schema', artifact={'tool_result_id': 'Told'}),
        HumanMessage(content='继续查询销售'),
        AIMessage(content='', tool_calls=[{'id': 'new', 'name': 'execute_readonly_sql', 'args': {}}]),
        ToolMessage(content='{"rows":[{"收入":"0.30"}]}', tool_call_id='new', name='execute_readonly_sql')]
    update = await middleware.abefore_model({'messages': messages}, None)
    retained = update['messages'][1:]
    assert len(retained) == len(messages)
    assert 'Told' in retained[2].content and 'context_pruned' in retained[2].content
    assert retained[2].artifact == {'tool_result_id': 'Told'}
    assert retained[-1].content == messages[-1].content
    assert retained[1].tool_calls[0]['id'] == retained[2].tool_call_id


@pytest.mark.asyncio
async def test_summary_carries_exact_reference_ids_even_if_model_omits_them(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_SUMMARY_TRIGGER_TOKENS', 2000)
    monkeypatch.setattr(settings, 'AGENT_SUMMARY_KEEP_TOKENS', 1000)
    model = ScriptedModel(respond=lambda messages: AIMessage(content='【条件与口径】2026年华东。'))
    middleware = ContextManagement(model, TokenBudget(64000, 32768), system_tokens=100, schema_tokens=100)
    messages = [HumanMessage(content='查询2026年收入'), AIMessage(content='结果 [查询 Qstable]')]
    for i in range(10):
        messages.extend([HumanMessage(content='继续分析'*200), AIMessage(content='业务说明'*200)])
    update = await middleware.abefore_model({'messages': messages}, None)
    summary = update['messages'][1].content
    assert 'Qstable' in summary


@pytest.mark.asyncio
async def test_table_only_query_reference_survives_in_next_turn(monkeypatch):
    seen = []
    def respond(messages):
        seen.append(messages)
        result = answer('已展示查询结果。')
        if len(seen) == 1:
            result['sections'][0].update(query_id='Qtable', show_table=True)
        else:
            assert any('Qtable' in str(message) for message in messages)
            assert any(isinstance(message, ToolMessage) for message in messages)
        return result
    install_model(monkeypatch, respond)
    thread = str(uuid.uuid4())
    executor = AgentExecutor('u', [], CFG)
    executor.sql.queries = [{'query_id': 'table', 'citation_id': 'Qtable', 'source_name': '销售',
                         'rows': [{'金额': '0.30'}], 'truncated': False}]
    first = await stream(executor, thread, '展示结果表格')
    assert presentation(first)['queries'][0]['rows'] == [{'金额': '0.30'}]
    await stream(AgentExecutor('u', [], CFG), thread, '读取刚才的精确数据')


@pytest.mark.asyncio
async def test_large_tool_error_is_also_bounded(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_TOOL_OUTPUT_TOKENS', 256)
    async def failing_tool() -> dict:
        """Return a verbose validation failure."""
        raise ValueError('字段校验失败：' * 3000)
    executor = AgentExecutor('u', [], CFG)
    message = await executor.sql.tool(failing_tool).ainvoke({'type': 'tool_call', 'id': 'failure', 'name': 'failing_tool', 'args': {}})
    preview = json.loads(message.content)
    assert serialized_tokens(preview) <= 256
    assert len(message.artifact['error']) > len(preview.get('error', ''))
    assert preview['tool_result_id'] in executor.sql.tool_results


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_response_merge_repeat_state(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_IDENTICAL_TOOL_CALLS', 2)
    def respond(messages):
        if not any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(content='', tool_calls=[
                {'id': f'resources{i}', 'name': 'list_available_resources', 'args': {}} for i in range(3)])
        assert sum(isinstance(message, ToolMessage) for message in messages) == 3
        assert sum('REPEATED_TOOL_CALL' in str(message.content) for message in messages) == 1
        return answer()
    install_model(monkeypatch, respond)
    executor = AgentExecutor('u', [], CFG)
    events = await stream(executor, str(uuid.uuid4()))
    assert events[-1]['type'] == 'RUN_FINISHED'
    assert executor.sql.calls == 2


@pytest.mark.asyncio
async def test_completed_repeat_counts_survive_worker_recovery(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_IDENTICAL_TOOL_CALLS', 2)
    import hashlib
    fingerprint = hashlib.sha256(json.dumps(['list_available_resources', {}], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def respond(messages):
        assert any(isinstance(message, ToolMessage) and 'REPEATED_TOOL_CALL' in message.content for message in messages)
        return answer()
    install_model(monkeypatch, respond)
    thread = str(uuid.uuid4())
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph = AgentExecutor('u', [], CFG).build_graph(saver)
        await graph.aupdate_state({'configurable': {'thread_id': thread}}, {
            'messages': [HumanMessage(id='original', content='继续分析'), AIMessage(content='', tool_calls=[
                {'id': 'duplicate', 'name': 'list_available_resources', 'args': {}}])],
            'execution_recent_calls': [fingerprint, fingerprint], 'execution_tool_calls': 2}, as_node='model')
    executor = AgentExecutor('u', [], CFG)
    events = await stream(executor, thread, recover=True, user_message_id='original')
    assert executor.sql.calls == 0
    assert events[-1]['type'] == 'RUN_FINISHED'
