"""Durable per-question loop guards, with one final answer opportunity."""
import hashlib
import json
import operator
from typing import Annotated
from typing_extensions import NotRequired
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.types import Command, Overwrite
from app.agents.errors import ExecutionLimitExceeded
from app.config import settings


def recent_calls(left, right):
    return [*(left or []), *(right or [])][-max(1, settings.AGENT_MAX_IDENTICAL_TOOL_CALLS):]


class ExecutionState(AgentState):
    execution_run_id: NotRequired[str]
    execution_model_calls: NotRequired[int]
    execution_accounted_id: NotRequired[str]
    execution_tool_calls: NotRequired[Annotated[int, operator.add]]
    execution_recent_calls: NotRequired[Annotated[list[str], recent_calls]]


class ExecutionControl(AgentMiddleware):
    state_schema = ExecutionState

    def __init__(self, run_id, fresh_turn):
        self.run_id, self.fresh_turn = run_id, fresh_turn
        self.reserved_tools = None
        self.recent = None

    async def abefore_agent(self, state, runtime):
        if self.fresh_turn and state.get('execution_run_id') != self.run_id:
            return {'execution_run_id': self.run_id, 'execution_model_calls': 0, 'execution_accounted_id': '',
                    'execution_tool_calls': Overwrite(0), 'execution_recent_calls': Overwrite([])}

    async def abefore_model(self, state, runtime):
        if state.get('execution_model_calls', 0) >= settings.AGENT_MAX_STEPS:
            raise ExecutionLimitExceeded('MODEL_CALL_LIMIT', '本轮模型调用达到保护上限，任务尚未完成。')

    async def awrap_model_call(self, request, handler):
        reason = None
        if request.state.get('execution_model_calls', 0) >= settings.AGENT_MAX_STEPS - 1:
            reason = 'MODEL_CALL_LIMIT'
        if request.state.get('execution_tool_calls', 0) >= settings.AGENT_MAX_TOOL_CALLS:
            reason = 'TOOL_CALL_LIMIT'
        if reason:
            request = request.override(tools=[], messages=[*request.messages, SystemMessage(content=
                '本轮执行达到保护边界。禁止继续查询，只使用已有证据输出最终结构化答案；明确说明已完成内容、未完成事项和限制，不编造新事实。')])
        response = await handler(request)
        if reason and any(call['name'] not in {'SuggestedAnswer', 'PlainAnswer'}
                          for message in response.result if isinstance(message, AIMessage) for call in message.tool_calls):
            raise ExecutionLimitExceeded(reason, '本轮执行达到保护上限，模型未能基于已有证据完成答案。')
        return response

    async def aafter_model(self, state, runtime):
        message = next((m for m in reversed(state['messages']) if isinstance(m, AIMessage)), None)
        if message and message.id != state.get('execution_accounted_id'):
            return {'execution_model_calls': state.get('execution_model_calls', 0) + 1,
                    'execution_accounted_id': message.id}

    async def awrap_tool_call(self, request, handler):
        if self.reserved_tools is None:
            self.reserved_tools = request.state.get('execution_tool_calls', 0)
            self.recent = list(request.state.get('execution_recent_calls', []))
        call = request.tool_call
        fingerprint = hashlib.sha256(json.dumps([call['name'], call['args']], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        repeated = len(self.recent) >= settings.AGENT_MAX_IDENTICAL_TOOL_CALLS and all(key == fingerprint for key in self.recent)
        exhausted = self.reserved_tools >= settings.AGENT_MAX_TOOL_CALLS
        self.reserved_tools += 1
        self.recent = [*self.recent, fingerprint][-settings.AGENT_MAX_IDENTICAL_TOOL_CALLS:]
        if repeated or exhausted:
            code = 'REPEATED_TOOL_CALL' if repeated else 'TOOL_CALL_LIMIT'
            result = ToolMessage(tool_call_id=call['id'], name=call['name'], status='error', content=json.dumps({
                'code': code, 'error': '调用没有进展或已达到工具上限。使用已有证据、调整参数或说明限制，不重复调用。'}, ensure_ascii=False))
        else:
            result = await handler(request)
        if isinstance(result, Command):
            return result
        return Command(update={'messages': [result], 'execution_tool_calls': 1,
                               'execution_recent_calls': [fingerprint]})
