"""Middleware nodes must not exhaust graph steps before the model-call budget."""
import uuid

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from app.agents.executor import AgentExecutor
from app.agents.errors import ExecutionLimitExceeded, classify_execution_error
from app.config import settings
from agent_helpers import CFG, answer, install_model


async def run(executor):
    return [event async for event in executor.stream('分析业务', thread_id=str(uuid.uuid4()),
        run_id='limits', user_message_id='question', assistant_message_id='response')]


def scripted(calls, finish_after=None):
    def respond(messages):
        calls.append(messages)
        completed = sum(isinstance(message, ToolMessage) for message in messages)
        if finish_after is not None and completed >= finish_after:
            return answer()
        # Distinct references avoid conflating repeated-tool protection with graph limits.
        return AIMessage(content='', tool_calls=[{'id': f'call-{completed}', 'name': 'read_tool_result',
            'args': {'tool_result_id': f'Tmissing{completed}'}}])
    return respond


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_graph_limit', [True, False])
async def test_twelve_model_calls_can_finish_with_all_context_hooks(monkeypatch, legacy_graph_limit):
    monkeypatch.setattr(settings, 'AGENT_MAX_STEPS', 12)
    calls = []
    install_model(monkeypatch, scripted(calls, finish_after=11))
    if legacy_graph_limit:
        monkeypatch.setattr('app.agents.executor.graph_recursion_limit', lambda graph, count: 58)
        with pytest.raises(ExecutionLimitExceeded) as error:
            await run(AgentExecutor('u', [], CFG))
        assert error.value.code == 'GRAPH_STEP_LIMIT'
        assert len(calls) < 12
        return
    events = await run(AgentExecutor('u', [], CFG))
    assert len(calls) == settings.AGENT_MAX_STEPS == 12
    assert events[-1]['type'] == 'RUN_FINISHED'


@pytest.mark.asyncio
async def test_model_limit_still_stops_loop_and_keeps_specific_error(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_STEPS', 3)
    calls = []
    install_model(monkeypatch, scripted(calls))
    with pytest.raises(ExecutionLimitExceeded) as error:
        await run(AgentExecutor('u', [], CFG))
    assert error.value.code == 'MODEL_CALL_LIMIT'
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_tool_limit_keeps_specific_error(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MAX_TOOL_CALLS', 2)
    install_model(monkeypatch, scripted([]))
    with pytest.raises(ExecutionLimitExceeded) as error:
        await run(AgentExecutor('u', [], CFG))
    assert error.value.code == 'TOOL_CALL_LIMIT'


def test_graph_limit_is_classified_without_exposing_provider_errors():
    assert classify_execution_error(GraphRecursionError('internal')).code == 'GRAPH_STEP_LIMIT'
    failure = RuntimeError('private provider detail')
    assert classify_execution_error(failure) is failure
