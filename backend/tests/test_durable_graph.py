import uuid
import pytest
from langchain_core.messages import AIMessage
from app.agents.executor import AgentExecutor
from agent_helpers import CFG,answer,install_model

@pytest.mark.asyncio
async def test_pending_tool_checkpoint_recovers_without_readding_user_input(monkeypatch):
    from app.config import settings
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain_core.messages import HumanMessage
    calls=[]
    def respond(messages):
        calls.append(messages)
        assert sum(message.type=='human' for message in messages)==1
        assert any(message.type=='tool' and message.name=='list_available_resources' for message in messages)
        return answer()
    install_model(monkeypatch,respond)
    thread=str(uuid.uuid4())
    config={'configurable':{'thread_id':thread}}
    settings.STORAGE_DIR.mkdir(parents=True,exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph=AgentExecutor('u',[],[],CFG).build_graph(saver)
        await graph.aupdate_state(config,{'messages':[
            HumanMessage(id='original',content='分析销售'),
            AIMessage(id='pending',content='',tool_calls=[{'id':'resources','name':'list_available_resources','args':{}}]),
        ]},as_node='model')
        assert (await graph.aget_state(config)).next
    events=[event async for event in AgentExecutor('u',[],[],CFG).stream('分析销售',
        thread_id=thread,run_id='r',user_message_id='original',assistant_message_id='a',recover=True)]
    assert len(calls)==1
    assert events[-1]['type']=='RUN_FINISHED'
    assert any(event['type']=='ACTIVITY_SNAPSHOT' for event in events)

@pytest.mark.asyncio
async def test_interrupt_survives_new_executor_and_resumes_once(monkeypatch):
    calls=[]
    def respond(messages):
        calls.append(messages)
        if not any(message.type=='tool' and message.name=='ask_clarification' for message in messages):
            return AIMessage(content='',tool_calls=[{'id':'clarify','name':'ask_clarification','args':{'question':'使用哪个业务年度？'}}])
        assert any('2026' in str(message.content) for message in messages)
        return answer('按2026年分析。')
    install_model(monkeypatch,respond)
    ids={'thread_id':str(uuid.uuid4()),'run_id':'r','user_message_id':'u','assistant_message_id':'a'}
    first=[e async for e in AgentExecutor('u',[],[],CFG).stream('分析销售',**ids)]
    assert first[-1]['type']=='RUN_FINISHED'
    assert first[-1]['outcome']['type']=='interrupt'
    interrupt=first[-1]['outcome']['interrupts'][0]
    assert interrupt['message']=='使用哪个业务年度？'
    second=[e async for e in AgentExecutor('u',[],[],CFG).stream('分析销售',**ids,
        resume=[{'interruptId':interrupt['id'],'status':'resolved','payload':'2026'}])]
    assert second[-1]['type']=='RUN_FINISHED'
    assert second[-1].get('outcome',{}).get('type','success')=='success'
    assert len(calls)==2

@pytest.mark.asyncio
async def test_completed_checkpoint_recovery_does_not_call_model_again(monkeypatch):
    calls=[]
    def respond(messages): calls.append(messages);return answer()
    install_model(monkeypatch,respond)
    ids={'thread_id':str(uuid.uuid4()),'run_id':'r','user_message_id':'u','assistant_message_id':'a'}
    first=[e async for e in AgentExecutor('u',[],[],CFG).stream('分析销售',**ids)]
    second=[e async for e in AgentExecutor('u',[],[],CFG).stream('分析销售',**ids,recover=True)]
    assert len(calls)==1
    assert next(e['delta'] for e in first if e['type']=='TEXT_MESSAGE_CONTENT')==next(e['delta'] for e in second if e['type']=='TEXT_MESSAGE_CONTENT')

@pytest.mark.asyncio
async def test_native_summary_compresses_checkpoint_but_keeps_corrected_conditions(monkeypatch,tmp_path):
    from app.config import settings
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain_core.messages import HumanMessage
    monkeypatch.setattr(settings,'AGENT_SUMMARY_TRIGGER_TOKENS',2000)
    monkeypatch.setattr(settings,'AGENT_SUMMARY_KEEP_TOKENS',1000)
    summary_calls=[]
    def respond(messages):
        if len(messages)==1 and '<role>' in str(messages[0].content):
            summary_calls.append(messages)
            return AIMessage(content='用户先说2025年，随后更正为2026年1月；区域华东；沿用更正后的条件。')
        assert any('2026年1月' in str(message.content) for message in messages)
        return answer('按更正后的2026年1月、华东范围分析。')
    install_model(monkeypatch,respond)
    thread=str(uuid.uuid4())
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph=AgentExecutor('u',[],[],CFG).build_graph(saver)
        messages=[HumanMessage(id='old',content='查询2025年华东销售额。'),AIMessage(id='old-a',content='记录条件。'),
            HumanMessage(id='correct',content='更正为2026年1月，区域仍为华东。'),AIMessage(id='correct-a',content='已更正。')]
        for i in range(20):messages.extend([HumanMessage(id=f'u{i}',content='继续说明业务口径。'*40),AIMessage(id=f'a{i}',content='口径仅用于业务说明。'*40)])
        await graph.aupdate_state({'configurable':{'thread_id':thread}},{'messages':messages})
    events=[e async for e in AgentExecutor('u',[],[],CFG).stream('沿用更正后的条件继续。',thread_id=thread,run_id='r',user_message_id='latest',assistant_message_id='latest-a')]
    assert summary_calls
    assert events[-1]['type']=='RUN_FINISHED'
    assert not any('用户先说2025年' in str(e) for e in events)
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR/'checkpoints.sqlite')) as saver:
        graph=AgentExecutor('u',[],[],CFG).build_graph(saver)
        state=await graph.aget_state({'configurable':{'thread_id':thread}})
        assert len(state.values['messages'])<len(messages)
        assert any('2026年1月' in str(m.content) for m in state.values['messages'])
