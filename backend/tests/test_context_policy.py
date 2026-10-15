"""Provider capacity, cache continuity, overflow recovery and durable loop limits."""
import hashlib
import json
import uuid
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.agents.budget import TokenBudget
from app.agents.context import ContextManagement
from app.agents.executor import AgentExecutor
from app.agents.limits import resolve_model_limits
from app.config import settings
from app.infrastructure.tokenization import count_message_tokens
from agent_helpers import CFG, answer, install_model, ScriptedModel


def test_capacity_is_provider_specific_and_explicitly_overridable(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_CONTEXT_TOKENS', None)
    official = {**CFG, 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model_id': 'qwen3.8-max'}
    limits = resolve_model_limits(official)
    assert (limits.context, limits.input, limits.output, limits.source) == (1_000_000, 991_808, 8192, 'bailian')
    proxy = resolve_model_limits({**official, 'base_url': 'https://provider.test/v1'})
    assert proxy.context == 131072 and proxy.source == 'fallback'
    configured = resolve_model_limits({**official, 'context_window': 262144, 'max_input_tokens': 200000, 'max_output_tokens': 4096})
    assert (configured.context, configured.input, configured.output) == (262144, 200000, 4096)
    monkeypatch.setattr(settings, 'AGENT_CONTEXT_TOKENS', 65536)
    assert resolve_model_limits(official).input == 65536 - 8192


def test_compaction_tracks_capacity_and_overhead(monkeypatch):
    model = ScriptedModel(respond=lambda messages: AIMessage(content='summary'))
    policy = ContextManagement(model, TokenBudget(0, 1_000_000, 8192, input_limit=991808), system_tokens=2000, schema_tokens=4000)
    assert policy.prune_threshold == 100000
    assert policy.summary_threshold == 200000
    assert policy.keep == ('tokens', 32000)


@pytest.mark.asyncio
async def test_fixed_overhead_is_rejected_without_wasting_a_summary():
    from app.agents.budget import BudgetExceeded
    model = ScriptedModel(respond=lambda messages: pytest.fail('Fixed overhead cannot be summarized away'))
    policy = ContextManagement(model, TokenBudget(0, 8192, 4096), system_tokens=3000, schema_tokens=2000)
    with pytest.raises(BudgetExceeded, match='固定系统提示'):
        await policy.abefore_model({'messages': [HumanMessage(content='hello')]}, None)


def test_measured_prefix_plus_delta_includes_cached_tokens_and_invalidates_on_change(caplog):
    caplog.set_level('INFO')
    budget = TokenBudget(0, 100000, model_key='provider:model')
    initial = [SystemMessage(content='fixed instructions'), HumanMessage(content='private question')]
    budget.on_chat_model_start({}, [initial], invocation_params={'tools': []}, run_id='r')
    reply = AIMessage(content='done', usage_metadata={'input_tokens': 50000, 'output_tokens': 20, 'total_tokens': 50020,
        'input_token_details': {'cache_read': 45000}})
    budget.on_llm_end(LLMResult(generations=[[ChatGeneration(message=reply)]]), run_id='r')
    schema_key = hashlib.sha256(json.dumps([], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    tail = HumanMessage(content='follow up')
    assert budget.estimate_input([*initial, reply, tail], 2, schema_key=schema_key) == 50020 + count_message_tokens([tail])
    changed = [SystemMessage(content='changed instructions'), *initial[1:], reply, tail]
    assert budget.estimate_input(changed, 2, schema_key=schema_key) < 50000
    budget.model_key = 'other:model'
    assert budget.estimate_input([*initial, reply, tail], 2, schema_key=schema_key) < 50000
    assert budget.cached_tokens == 45000 and budget.spent == 50020
    assert 'cached_tokens=45000' in caplog.text and 'private question' not in caplog.text


async def stream(executor, thread, query='分析业务', **kwargs):
    return [event async for event in executor.stream(query, thread_id=thread,
        run_id=kwargs.pop('run_id', str(uuid.uuid4())), user_message_id=kwargs.pop('user_message_id', str(uuid.uuid4())),
        assistant_message_id=str(uuid.uuid4()), **kwargs)]


@pytest.mark.asyncio
async def test_runtime_changes_append_without_rewriting_previous_provider_messages(monkeypatch):
    requests = []
    def respond(messages):
        requests.append(deepcopy(messages))
        return answer()
    install_model(monkeypatch, respond)
    thread = str(uuid.uuid4())
    await stream(AgentExecutor('u', [], CFG), thread, memory='简短')
    await stream(AgentExecutor('u', [], CFG), thread, memory='详细')
    assert requests[1][:len(requests[0])] == requests[0]
    assert '详细' in requests[1][-2].content
    assert requests[0][0].content == requests[1][0].content


@pytest.mark.asyncio
async def test_summary_retains_current_question_and_complete_tool_pairs(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_SUMMARY_TRIGGER_TOKENS', 2000)
    monkeypatch.setattr(settings, 'AGENT_SUMMARY_KEEP_TOKENS', 256)
    model = ScriptedModel(respond=lambda messages: AIMessage(content='【条件与口径】以最新更正为准。'))
    policy = ContextManagement(model, TokenBudget(0, 32768), system_tokens=100, schema_tokens=100)
    question = HumanMessage(id='latest', content='必须使用2026年华东口径，不要沿用2025年。')
    messages = [HumanMessage(id='old', content='以前的问题'*1000), AIMessage(content='旧分析'*1000), question]
    for i in range(4):
        messages.extend([AIMessage(content='', tool_calls=[{'id': f't{i}', 'name': 'query', 'args': {}}]),
            ToolMessage(content='结果说明'*1000, tool_call_id=f't{i}', name='query')])
    update = await policy.abefore_model({'messages': messages}, None)
    retained = update['messages'][1:]
    assert any(message.id == question.id and message.content == question.content for message in retained)
    calls = {call['id'] for message in retained if isinstance(message, AIMessage) for call in message.tool_calls}
    assert all(message.tool_call_id in calls for message in retained if isinstance(message, ToolMessage))


@pytest.mark.asyncio
@pytest.mark.parametrize('reject_retry', [False, True])
async def test_provider_overflow_compacts_once_and_checkpoints_recovered_context(monkeypatch, reject_retry):
    from app.agents.budget import BudgetExceeded
    requests = []
    def provider(request):
        payload = json.loads(request.content)
        requests.append(payload)
        summary = len(payload['messages']) == 1 and '<role>' in str(payload['messages'][0]['content'])
        if summary:
            delta = {'role': 'assistant', 'content': '【目标】继续业务分析。'}
            finish = 'stop'
        elif len(requests) == 1 or reject_retry:
            return httpx.Response(400, json={'error': {'code': 'context_length_exceeded', 'message': 'too long', 'type': 'invalid_request_error'}})
        else:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'finished', 'type': 'function',
                'function': {'name': 'SuggestedAnswer', 'arguments': json.dumps(answer())}}]}
            finish = 'tool_calls'
        chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'test',
                 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
        end = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text=f'data: {json.dumps(chunk)}\n\ndata: {json.dumps(end)}\n\ndata: [DONE]\n\n')
    thread = str(uuid.uuid4())
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph = AgentExecutor('u', [], CFG).build_graph(saver)
        await graph.aupdate_state({'configurable': {'thread_id': thread}}, {'messages': [
            HumanMessage(id='old', content='以前的任务'*1000), AIMessage(content='已完成旧分析'*1000)]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        monkeypatch.setattr('langchain_openai.ChatOpenAI', lambda **kw: ChatOpenAI(**kw, http_async_client=client))
        if reject_retry:
            with pytest.raises(BudgetExceeded) as error:
                await stream(AgentExecutor('u', [], CFG), thread)
            assert error.value.code == 'CONTEXT_TOKEN_LIMIT'
        else:
            events = await stream(AgentExecutor('u', [], CFG), thread)
            assert events[-1]['type'] == 'RUN_FINISHED'
            async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
                graph = AgentExecutor('u', [], CFG).build_graph(saver)
                state = await graph.aget_state({'configurable': {'thread_id': thread}})
                assert any('【目标】继续业务分析' in str(m.content) for m in state.values['messages'])
                assert not any(m.id == 'old' for m in state.values['messages'])
                assert state.values['structured_response'] is not None
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_last_model_call_can_finish_with_only_the_answer_tool(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_STEPS', 1)
    payloads = []
    def provider(request):
        payload = json.loads(request.content); payloads.append(payload)
        assert [tool['function']['name'] for tool in payload['tools']] == ['SuggestedAnswer']
        chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'done',
                'type': 'function', 'function': {'name': 'SuggestedAnswer', 'arguments': json.dumps(answer())}}]}, 'finish_reason': None}]}
        end = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text=f'data: {json.dumps(chunk)}\n\ndata: {json.dumps(end)}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        monkeypatch.setattr('langchain_openai.ChatOpenAI', lambda **kw: ChatOpenAI(**kw, http_async_client=client))
        events = await stream(AgentExecutor('u', [], CFG), str(uuid.uuid4()))
    assert len(payloads) == 1 and events[-1]['type'] == 'RUN_FINISHED'


@pytest.mark.asyncio
async def test_durable_model_count_survives_worker_restart(monkeypatch):
    from app.agents.errors import ExecutionLimitExceeded
    monkeypatch.setattr(settings, 'AGENT_MAX_STEPS', 3)
    install_model(monkeypatch, lambda messages: pytest.fail('A restarted worker must not get a fresh allowance'))
    thread = str(uuid.uuid4())
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph = AgentExecutor('u', [], CFG).build_graph(saver)
        await graph.aupdate_state({'configurable': {'thread_id': thread}}, {'messages': [HumanMessage(id='question', content='继续')],
            'execution_model_calls': 3, 'execution_run_id': 'same-run'})
    with pytest.raises(ExecutionLimitExceeded) as error:
        await stream(AgentExecutor('u', [], CFG), thread, recover=True, run_id='same-run', user_message_id='question')
    assert error.value.code == 'MODEL_CALL_LIMIT'
