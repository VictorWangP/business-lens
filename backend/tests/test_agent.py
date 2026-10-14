"""Real graph, durable worker, Docling, SQL and retrieval with only provider substitutes."""
import json
import uuid
import asyncio
import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from sqlalchemy import select
from app.agents.executor import AgentExecutor
from app.database import AsyncSessionLocal
from app.models.platform import AgentRun,RunEvent,IngestionJob
from app.services.llm_service import LLMService
from app.infrastructure.embeddings import EmbeddingProvider
from app.ingestion.pipeline import ingest
from agent_helpers import CFG,answer,install_model,chat_input,read_events,presentation
from test_platform import seed,auth
from test_tabular import CSV
from main import app

@pytest_asyncio.fixture(autouse=True)
async def worker(database):
    from app.workers.local import run_agent_worker
    task=asyncio.create_task(run_agent_worker())
    yield
    task.cancel();await asyncio.gather(task,return_exceptions=True)

async def workspace(client,headers,kb_ids=(),source_ids=()):
    result=await client.post('/api/workspaces',headers=headers,json={'name':'测试空间','kb_ids':list(kb_ids),'source_ids':list(source_ids)})
    assert result.status_code==200,result.text
    return result.json()['id']

async def configure(monkeypatch):
    async def config(*args,**kwargs): return CFG
    monkeypatch.setattr(LLMService,'get_model_config',config)

def scripted(tools,text):
    def respond(messages):
        count=sum(m.type=='tool' and m.name not in {'SuggestedAnswer','PlainAnswer'} for m in messages)
        if count<len(tools):
            name,args=tools[count]
            return AIMessage(content='内部图表配置不得显示',tool_calls=[{'id':f'call-{count}','name':name,'args':args}])
        rendered=text
        for message in messages:
            if message.type=='tool':
                try:
                    result=json.loads(message.content)
                    if result.get('citation_id'): rendered=rendered.replace('Q1',result['citation_id'])
                    if result.get('citations'): rendered=rendered.replace('S1',result['citations'][0]['id'])
                except (ValueError,TypeError): pass
        return answer(rendered)
    return respond

@pytest.mark.asyncio
async def test_docling_sql_joint_answer_and_idempotent_replay(monkeypatch):
    uid,_,kb_id=await seed();await configure(monkeypatch)
    async def embedding_config(cls,db,user_id):return cls({'base_url':'http://test/v1','model_id':'offline-embedding','api_key':'test'})
    async def embedding(self,texts):return [[1.,0.,0.] for _ in texts]
    monkeypatch.setattr(EmbeddingProvider,'for_user',classmethod(embedding_config))
    monkeypatch.setattr(EmbeddingProvider,'embed',embedding)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=auth(uid)) as client:
        imported=await client.post('/api/data-sources/import',data={'name':'订单'},files={'file':('orders.csv',CSV,'text/csv')})
        assert imported.status_code==200,imported.text
        sid=imported.json()['id']
        uploaded=await client.post(f'/api/knowledge/bases/{kb_id}/documents/upload',files={'file':('policy.md','# 华东折扣政策\n\n折扣为5%，需主管审批；审批规则适用于华东客户。'.encode(),'text/markdown')})
        async with AsyncSessionLocal() as db:
            job=await db.scalar(select(IngestionJob).where(IngestionJob.doc_id==uploaded.json()['id']))
            job_id,chunk_id=job.id,job.version+'_0'
        await ingest(job_id)
        tools=[('list_available_resources',{}),('get_business_schema',{'source_id':sid}),
            ('execute_readonly_sql',{'source_id':sid,'sql':"SELECT SUM(amount) AS total FROM dataset WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-02-01'"}),
            ('search_knowledge',{'query':'华东折扣政策'}),('search_knowledge',{'query':'折扣主管审批规则'}),
            ('read_document_section',{'chunk_id':chunk_id})]
        install_model(monkeypatch,scripted(tools,'一月销售额为0.30 [查询 Q1]。华东折扣需主管审批 [来源 S1]。'))
        wid=await workspace(client,auth(uid),[kb_id],[sid]);payload=chat_input('汇总一月销售额，检索折扣政策',wid)
        response=await client.post('/api/chat/stream',json=payload)
        assert response.status_code==200,response.text
        events=read_events(response)
        assert events[-1]['type']=='RUN_FINISHED',events
        data=presentation(events)
        assert data['queries'][0]['rows']==[{'total':'0.30'}]
        assert data['citations'][0]['headings']==['华东折扣政策']
        assert data['citations'][0]['chunk_id']==chunk_id
        assert [e['toolCallName'] for e in events if e['type']=='TOOL_CALL_START']==[name for name,_ in tools]
        assert '内部图表配置不得显示' not in response.text
        assert all(e.get('delta')=='{}' for e in events if e['type']=='TOOL_CALL_ARGS')
        replay=await client.post('/api/chat/stream',json=payload)
        assert read_events(replay)==events
        async with AsyncSessionLocal() as db:
            runs=(await db.scalars(select(AgentRun))).all();assert len(runs)==1 and runs[0].attempts==1

@pytest.mark.parametrize('chart_word,expected',[('折线图','line'),('折线图，不要输出绘图代码','line'),('饼图','pie'),('环形图','pie'),('柱状图','bar'),('列出月份和金额',None),('不要图表，只用表格',None)])
@pytest.mark.asyncio
async def test_charts_are_exact_data_parts(monkeypatch,chart_word,expected):
    uid,_,_=await seed();await configure(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=auth(uid)) as client:
        imported=await client.post('/api/data-sources/import',data={'name':'月度销售'},files={'file':('orders.csv',CSV,'text/csv')});sid=imported.json()['id']
        tools=[('get_business_schema',{'source_id':sid}),('execute_readonly_sql',{'source_id':sid,'sql':"SELECT SUBSTRING(CAST(order_date AS VARCHAR),1,7) AS month,SUM(amount) AS revenue FROM dataset GROUP BY month ORDER BY month"})]
        install_model(monkeypatch,scripted(tools,'已汇总各月销售收入 [查询 Q1]。'))
        wid=await workspace(client,auth(uid),source_ids=[sid]);response=await client.post('/api/chat/stream',json=chat_input('按月汇总，用'+chart_word+'展示',wid))
        events=read_events(response);assert events[-1]['type']=='RUN_FINISHED',events
        chart=presentation(events)['queries'][0]['chart']
        assert (chart['type'] if chart else None)==expected
        if chart: assert chart['data']==[{'month':'2026-01','revenue':0.3},{'month':'2026-02','revenue':100.0}]

@pytest.mark.asyncio
async def test_native_limits_bound_repeated_tool_calls(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'AGENT_MAX_TOOL_CALLS',2)
    install_model(monkeypatch,lambda messages:AIMessage(content='',tool_calls=[{'id':str(uuid.uuid4()),'name':'list_available_resources','args':{}}]))
    executor=AgentExecutor('user',[],[],CFG)
    with pytest.raises(RuntimeError):
        async for _ in executor.stream('查询',thread_id=str(uuid.uuid4()),run_id='r',user_message_id='u',assistant_message_id='a'): pass
    assert executor.calls==2
@pytest.mark.parametrize('kind, disabled, rows, truncated, expected', [
    ('none', False, [{'region': '华东', 'revenue': 10}, {'region': '华北', 'revenue': 20}], False, None),
    ('bar', False, [{'region': '华东', 'revenue': 10}, {'region': '华北', 'revenue': 20}], False, 'bar'),
    ('line', True, [{'month': '一月', 'revenue': 10}, {'month': '二月', 'revenue': 20}], False, None),
    ('bar', False, [{'region': '华东', 'revenue': 10}], False, None),
    ('bar', False, [{'region': '华东', 'revenue': 10}, {'region': '华北', 'revenue': 20}], True, None),
])
@pytest.mark.asyncio
async def test_query_only_emits_suitable_requested_charts(monkeypatch, kind, disabled, rows, truncated, expected):
    from types import SimpleNamespace
    async def execute(*args):
        return {'rows': rows, 'truncated': truncated}
    monkeypatch.setattr('app.agents.executor.execute', execute)
    executor = AgentExecutor('user', [], [], {})
    executor.charts_disabled = disabled
    await executor.query(SimpleNamespace(id='source', name='销售'), 'SELECT ...', chart_type=kind)
    events = []
    while not executor.pending.empty():
        events.append(executor.pending.get_nowait())
    assert events[0]['type'] == 'query_result'
    charts = [event['chart'] for event in events if event['type'] == 'query_result' and event.get('chart')]
    assert [chart['type'] for chart in charts] == ([expected] if expected else [])

@pytest.mark.asyncio
async def test_http_pause_resume_replay_is_self_contained_and_idempotent(monkeypatch):
    uid,_,kb=await seed();await configure(monkeypatch)
    def respond(messages):
        if not any(m.type=='tool' and m.name=='ask_clarification' for m in messages):
            return AIMessage(content='',tool_calls=[{'id':'clarify','name':'ask_clarification','args':{'question':'使用哪个年度？'}}])
        return answer('按2026年分析。')
    install_model(monkeypatch,respond)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=auth(uid)) as client:
        wid=await workspace(client,auth(uid),[kb]);payload=chat_input('分析销售',wid)
        first=await client.post('/api/chat/stream',json=payload);first_events=read_events(first)
        assert first_events[-1]['outcome']['type']=='interrupt',first_events
        item=first_events[-1]['outcome']['interrupts'][0]
        resumed={**payload,'runId':str(uuid.uuid4()),'resume':[{'interruptId':item['id'],'status':'resolved','payload':'2026'}]}
        invalid={**resumed,'resume':[{'interruptId':item['id'],'status':'resolved','payload':{'unexpected':'object'}}]}
        assert (await client.post('/api/chat/stream',json=invalid)).status_code==422
        second=await client.post('/api/chat/stream',json=resumed);events=read_events(second)
        assert [e['type'] for e in events].count('RUN_STARTED')==1
        assert [e['type'] for e in events].count('RUN_FINISHED')==1
        assert events[-1]['runId']==resumed['runId']
        assert events[-1].get('outcome',{}).get('type','success')=='success'
        assert any(item['type']=='tool_end' for item in presentation(events)['operations'])
        assert next(e['messageId'] for e in events if e['type']=='TEXT_MESSAGE_START')!=next(e['parentMessageId'] for e in first_events if e['type']=='TOOL_CALL_START')
        duplicate=await client.post('/api/chat/stream',json=resumed)
        assert read_events(duplicate)==events
        async with AsyncSessionLocal() as db:
            run=await db.get(AgentRun,payload['runId']);assert run.status=='completed' and run.attempts==2
        from pathlib import Path
        Path('/tmp/rag-langgraph-agui-pause-fixture.json').write_text(json.dumps({'first':first_events,'second':events},ensure_ascii=False))
