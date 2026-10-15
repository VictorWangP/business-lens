"""Exercise the real LangChain/OpenAI request and AG-UI completion boundaries."""
import json
import uuid

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents.executor import AgentExecutor
from app.agents.answer import FinalAnswer
from agent_helpers import CFG, answer, presentation


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('base_url,model_studio', [
    ('https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', True),
    ('https://dashscope.aliyuncs.com/compatible-mode/v1', True),
    ('https://dashscope-intl.aliyuncs.com/compatible-mode/v1', True),
    ('https://dashscope-us.aliyuncs.com/compatible-mode/v1', True),
    ('https://provider.test/v1', False),
    ('https://dashscope.aliyuncs.com.provider.test/v1', False),
])
@pytest.mark.asyncio
async def test_required_tools_complete_without_thinking_conflict(monkeypatch, base_url, model_studio, enabled):
    requests = []

    def provider(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload['tool_choice'] == 'required'
        assert payload['parallel_tool_calls'] is False
        if model_studio and payload.get('enable_thinking') is not False:
            return httpx.Response(400, json={'error': {
                'message': 'The tool_choice parameter does not support being set to required or object in thinking mode',
                'type': 'invalid_request_error'}})
        if not model_studio:
            assert 'enable_thinking' not in payload
        names = {tool['function']['name'] for tool in payload['tools']}
        final_tool = 'SuggestedAnswer' if enabled else 'PlainAnswer'
        assert {'list_available_resources', final_tool} <= names
        if len(requests) == 1:
            name, args = 'list_available_resources', {}
        else:
            assert any(message.get('role') == 'tool' for message in payload['messages'])
            name, args = final_tool, answer(enabled=enabled)
        chunk = {'id': 'chatcmpl-test', 'object': 'chat.completion.chunk', 'created': 0,
                 'model': 'qwen-test', 'choices': [{'index': 0, 'delta': {'role': 'assistant',
                     'tool_calls': [{'index': 0, 'id': f'call-{len(requests)}', 'type': 'function',
                                     'function': {'name': name, 'arguments': json.dumps(args)}}]},
                     'finish_reason': None}]}
        end = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text=f'data: {json.dumps(chunk)}\n\ndata: {json.dumps(end)}\n\ndata: [DONE]\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        monkeypatch.setattr('langchain_openai.ChatOpenAI',
                            lambda **kwargs: ChatOpenAI(**kwargs, http_async_client=client))
        executor = AgentExecutor('u', [], {**CFG, 'base_url': base_url}, enable_suggestions=enabled)
        events = [event async for event in executor.stream(
            '查看可用资源', thread_id=str(uuid.uuid4()), run_id='r',
            user_message_id='u1', assistant_message_id='a1')]

    assert len(requests) == 2
    assert events[-1]['type'] == 'RUN_FINISHED'
    assert [event['toolCallName'] for event in events if event['type'] == 'TOOL_CALL_START'] == ['list_available_resources']
    assert presentation(events)['answer'] == FinalAnswer.model_validate(answer(enabled=enabled)).model_dump()
