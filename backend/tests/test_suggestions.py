"""Native structured output, safe projection, archive and suggestions switch."""
import json
import uuid
import pytest
from langchain_core.messages import AIMessage
from app.agents.executor import AgentExecutor
from app.agents.answer import AnswerValidationError
from app.application.chat import prepare_chat,execute_agent_run
from app.database import AsyncSessionLocal
from app.models.platform import AgentRun, DataSource
from app.models.conversation import Message,BusinessWorkspace
from app.models.user import User
from app.models.config import AppConfig
from app.schemas.chat import ChatRequest
from app.services.llm_service import LLMService
from agent_helpers import CFG,QUESTIONS,answer,install_model,presentation

async def stream(executor):
    return [e async for e in executor.stream('分析经营情况',thread_id=str(uuid.uuid4()),run_id=str(uuid.uuid4()),
        user_message_id=str(uuid.uuid4()),assistant_message_id=str(uuid.uuid4()))]

@pytest.mark.asyncio
async def test_valid_delivery_uses_native_structured_output(monkeypatch):
    calls=[]
    def respond(messages): calls.append(messages);return answer()
    install_model(monkeypatch,respond)
    events=await stream(AgentExecutor('u', [],CFG))
    assert presentation(events)['answer']['suggestions']==QUESTIONS
    assert len(calls)==1
    assert [e['delta'] for e in events if e['type']=='TEXT_MESSAGE_CONTENT']==['## 1. 业务分析\n\n当前数据不足以确认增长。']
    assert not any(e['type'] in {'RAW','MESSAGES_SNAPSHOT','STATE_SNAPSHOT'} for e in events)

@pytest.mark.asyncio
async def test_native_schema_retries_invalid_code_without_leaking(monkeypatch):
    calls=[]
    def respond(messages):
        calls.append(messages)
        return answer('```python\nprint(123)\n```') if len(calls)==1 else answer()
    install_model(monkeypatch,respond)
    events=await stream(AgentExecutor('u', [],CFG))
    assert len(calls)==2
    assert 'print(123)' not in json.dumps(events)
    assert events[-1]['type']=='RUN_FINISHED'

@pytest.mark.asyncio
async def test_plain_model_draft_never_becomes_public_text(monkeypatch):
    install_model(monkeypatch,lambda messages:AIMessage(content='```mermaid\nxychart-beta\nline [1,2]\n```'))
    events=[]
    with pytest.raises(AnswerValidationError):
        async for event in AgentExecutor('u', [],CFG).stream('画折线图',thread_id=str(uuid.uuid4()),run_id='r',user_message_id='u1',assistant_message_id='a1'):
            events.append(event)
    assert 'xychart' not in json.dumps(events)

@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.asyncio
async def test_delivery_persistence_and_switch(monkeypatch,enabled):
    async with AsyncSessionLocal() as db:
        user=User(username='answer-user',hashed_password='unused');db.add(user);await db.flush()
        source=DataSource(user_id=user.id,name='数据源',connection_secret='unused');db.add(source);await db.flush()
        ws=BusinessWorkspace(user_id=user.id,name='空间',source_ids=json.dumps([source.id]));db.add(ws);await db.flush()
        db.add(AppConfig(user_id=user.id,config_key='next_questions',is_enabled=enabled,config_value='{}'));await db.commit()
        uid,wid=user.id,ws.id
    async def config(*args,**kwargs):return CFG
    monkeypatch.setattr(LLMService,'get_model_config',config)
    install_model(monkeypatch,lambda messages:answer(enabled=enabled))
    async with AsyncSessionLocal() as db:
        run=await prepare_chat(db,uid,ChatRequest(query='查看业务情况',workspace_id=wid));rid=run.id
    await execute_agent_run(rid)
    async with AsyncSessionLocal() as db:
        run=await db.get(AgentRun,rid);assert run.status=='completed'
        message=await db.get(Message,run.assistant_message_id)
        saved=json.loads(message.tool_calls)
        assert saved['presentation']['answer']['suggestions']==(QUESTIONS if enabled else [])
        assert message.content.startswith('## 1. 业务分析')
