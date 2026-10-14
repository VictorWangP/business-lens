"""Final-answer protocol through the actual workflow and message persistence."""
import json
import pytest
from llama_index.core.llms import MockFunctionCallingLLM
from llama_index.core.base.llms.types import ChatMessage
from sqlalchemy import select
from app.agents.executor import AgentExecutor
from app.agents.answer import AnswerValidationError
from app.models.platform import AgentRun, RunEvent
from app.models.conversation import Message as SavedMessage, BusinessWorkspace
from app.models.config import AppConfig
from app.models.user import User
from app.models.knowledge import KnowledgeBase
from app.database import AsyncSessionLocal
from app.services.llm_service import LLMService
from app.schemas.chat import ChatRequest
from app.application.chat import prepare_chat, execute_agent_run

CFG = {'model_id':'test','base_url':'http://test/v1','api_key':'key','temperature':0}
QUESTIONS = ['查看成本明细', '比较业务差异', '进一步解释口径']

def delivery(enabled=True):
    return json.dumps({'version':1,'sections':[{'title':'业务分析','summary':'当前数据不足以确认增长。'}],
                       'suggestions':QUESTIONS if enabled else []}, ensure_ascii=False)


def install_model(monkeypatch, replies):
    calls = []
    def respond(messages, **kwargs):
        calls.append(messages)
        return ChatMessage(role='assistant',content=replies[min(len(calls)-1, len(replies)-1)])
    model = MockFunctionCallingLLM(response_generator=respond,is_chat_model=True)
    monkeypatch.setattr('app.agents.executor.OpenAILike',lambda **kwargs:model)
    return calls


@pytest.mark.asyncio
async def test_valid_delivery_uses_one_call_and_one_answer_event(monkeypatch):
    calls = install_model(monkeypatch,[delivery()])
    events = [event async for event in AgentExecutor('user',[],[],CFG).stream('分析经营情况',[])]
    answer = next(event for event in events if event['type']=='answer')
    assert answer['answer']['suggestions']==QUESTIONS
    assert answer['content']=='## 1. 业务分析\n\n当前数据不足以确认增长。'
    assert len(calls)==1
    assert not any(event['type'] in {'chunk','suggestions'} for event in events)


@pytest.mark.asyncio
async def test_invalid_mermaid_draft_is_repaired_once_without_leaking(monkeypatch):
    calls = install_model(monkeypatch,['```mermaid\nxychart-beta\nline [1,2]\n```',delivery()])
    events = [event async for event in AgentExecutor('user',[],[],CFG).stream('绘制折线图',[])]
    assert len(calls)==2
    assert not any('xychart' in event.get('content','') for event in events)
    assert next(event for event in events if event['type']=='answer')['answer']['suggestions']==QUESTIONS


@pytest.mark.asyncio
async def test_repeated_invalid_output_fails_explicitly(monkeypatch):
    calls = install_model(monkeypatch,['无效回答，不是 JSON'])
    events=[]
    with pytest.raises(AnswerValidationError):
        async for event in AgentExecutor('user',[],[],CFG).stream('分析经营情况',[]):
            events.append(event)
    assert len(calls)==2
    assert not any(event['type'] in {'answer','chunk'} for event in events)


@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.asyncio
async def test_delivery_persistence_and_historical_messages(monkeypatch,enabled):
    async with AsyncSessionLocal() as db:
        user=User(username='answer-user',hashed_password='unused');db.add(user);await db.flush()
        kb=KnowledgeBase(user_id=user.id,name='文档');db.add(kb);await db.flush()
        ws=BusinessWorkspace(user_id=user.id,name='空间',kb_ids=json.dumps([kb.id]),source_ids='[]');db.add(ws);await db.flush()
        db.add(AppConfig(user_id=user.id,config_key='next_questions',is_enabled=enabled,config_value='{"count":3}'))
        await db.commit()
        uid,wid=user.id,ws.id
    async def config(*args,**kwargs):return CFG
    monkeypatch.setattr(LLMService,'get_model_config',config)
    calls=install_model(monkeypatch,[delivery(enabled)])
    async with AsyncSessionLocal() as db:
        run=await prepare_chat(db,uid,ChatRequest(query='查看业务情况',workspace_id=wid));rid=run.id
    await execute_agent_run(rid)
    async with AsyncSessionLocal() as db:
        events=(await db.scalars(select(RunEvent).where(RunEvent.run_id==rid).order_by(RunEvent.sequence))).all()
        done=next(event.payload for event in events if event.event_type=='done')
        assert done['status']=='completed'
        run=await db.get(AgentRun,rid)
        message=await db.get(SavedMessage,run.assistant_message_id)
        saved=json.loads(message.tool_calls)
        assert saved['answer']['suggestions']==(QUESTIONS if enabled else [])
        assert 'suggestions' not in saved
        assert message.content.startswith('## 1. 业务分析')
        assert len(calls)==1
        if enabled:assert done['suggestions']==QUESTIONS
        else:assert 'suggestions' not in done
