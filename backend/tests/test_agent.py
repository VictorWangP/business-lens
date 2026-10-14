"""Deterministic provider substitutes validate the real LlamaIndex workflow, not production data accuracy."""
import json
import asyncio
import pytest
import pytest_asyncio
import httpx
from llama_index.core.llms import MockFunctionCallingLLM
from llama_index.core.base.llms.types import ChatMessage, ToolCallBlock
from sqlalchemy import select
from app.agents.executor import AgentExecutor
from app.models.platform import AgentRun, RunEvent
from app.models.user import User
from app.models.knowledge import KnowledgeBase
from app.database import AsyncSessionLocal
from app.security.auth import create_access_token
from app.services.llm_service import LLMService
from app.services.rag_service import RAGService
from app.schemas.chat import CitationItem
from main import app

@pytest_asyncio.fixture(autouse=True)
async def agent_worker(database):
    # ASGITransport does not run the separate production worker. Exercise the
    # actual database queue rather than leaving streaming requests queued forever.
    from app.workers.local import run_agent_worker
    task = asyncio.create_task(run_agent_worker())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

def delivery(text):
    return json.dumps({'version': 1, 'sections': [{'title': '分析结果', 'summary': text}],
                       'suggestions': ['查看明细', '比较各项差异', '进一步说明业务口径']}, ensure_ascii=False)

def read_events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]

async def workspace(client, headers, kb_ids=(), source_ids=()):
    response = await client.post('/api/workspaces', headers=headers, json={'name':'测试业务空间','kb_ids':list(kb_ids),'source_ids':list(source_ids)})
    assert response.status_code == 200, response.text
    return response.json()['id']

@pytest.mark.asyncio
async def test_llamaindex_performs_multiple_retrievals_and_persists_evidence(monkeypatch):
    async with AsyncSessionLocal() as db:
        user = User(username='analyst', hashed_password='unused'); db.add(user); await db.flush()
        kb = KnowledgeBase(user_id=user.id, name='政策'); db.add(kb); await db.commit()
        uid, kb_id = user.id, kb.id
    calls = []
    async def retrieve(user_id, kb_ids, query, top_k=6):
        assert user_id == uid and kb_ids == [kb_id]
        calls.append(query)
        return [CitationItem(id=f'chunk{len(calls)}', chunk_id=f'chunk{len(calls)}', doc_id='doc', doc_name='policy.pdf',
                             chunk_index=len(calls)-1, content='折扣需要主管审批' if len(calls)==1 else '主管审批适用于华东客户', score=0.03)]
    monkeypatch.setattr(RAGService, 'query_knowledge_bases', retrieve)
    async def config(*args, **kwargs):
        return {'model_id':'test', 'base_url':'http://test/v1','api_key':'test','temperature':0}
    monkeypatch.setattr(LLMService, 'get_model_config', config)
    prompts = []
    def response(messages, **kwargs):
        prompts.append(messages)
        count = sum(1 for m in messages if str(m.role) == 'MessageRole.TOOL' or m.role == 'tool')
        if count == 0:
            return ChatMessage(role='assistant', blocks=[ToolCallBlock(tool_name='search_knowledge', tool_call_id='call1', tool_kwargs={'query':'华东折扣'})])
        if count == 1:
            return ChatMessage(role='assistant', blocks=[ToolCallBlock(tool_name='search_knowledge', tool_call_id='call2', tool_kwargs={'query':'主管审批适用客户'})])
        return ChatMessage(role='assistant', content=delivery('华东折扣需要主管审批 [来源 S1] [来源 S2]'))
    llm = MockFunctionCallingLLM(response_generator=response, is_chat_model=True)
    monkeypatch.setattr('app.agents.executor.OpenAILike', lambda **kwargs: llm)
    headers = {'Authorization':'Bearer '+create_access_token({'sub':uid})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        wid = await workspace(client, headers, [kb_id])
        r = await client.post('/api/chat/stream', headers=headers, json={'query':'华东折扣适用什么审批？','workspace_id':wid})
        assert r.status_code == 200, r.text
        events = read_events(r)
        assert events[-1]['status'] == 'completed', events
        assert calls == ['华东折扣','主管审批适用客户']
        assert len([e for e in events if e['type']=='tool_start']) == 2
        assert len([e for e in events if e['type']=='citations'][-1]['items']) == 2
        run_id = events[-1]['run_id']
        saved = await client.get(f'/api/runs/{run_id}', headers=headers)
        assert saved.json()['run']['status'] == 'completed'
        assert any(e['type']=='tool_end' for e in saved.json()['events'])
        # RAG follow-ups receive previous user and assistant turns.
        await client.post('/api/chat/stream', headers=headers, json={'query':'再详细解释', 'conversation_id': next(e['conversation_id'] for e in events if e['type'] == 'run_started')})
        assert any(m.content and '华东折扣适用什么审批' in m.content for m in prompts[-1])

@pytest.mark.asyncio
async def test_repetition_budget_returns_explicit_error():
    executor = AgentExecutor('u', [], [], {})
    async def lookup(query: str):
        return {'query':query}
    tool = executor.tool(lookup)
    await tool.acall(query='same')
    await tool.acall(query='same')
    third = await tool.acall(query='same')
    assert '重复调用' in third.content
    assert executor.errors == 1

@pytest.mark.asyncio
async def test_full_file_docling_agent_flow_uses_persisted_evidence(monkeypatch):
    """Actual parsing, stores, retrieval and DuckDB; only external model transports substituted."""
    from app.infrastructure.embeddings import EmbeddingProvider
    from app.ingestion.pipeline import ingest
    from app.models.platform import IngestionJob
    from test_platform import seed, auth
    from test_tabular import CSV
    uid, _, kb_id = await seed()
    async def embedding_config(cls, db, user_id):
        return cls({'base_url':'http://test/v1','model_id':'offline-embedding','api_key':'test'})
    async def embedding(self, texts):
        return [[1.,0.,0.] for _ in texts]
    monkeypatch.setattr(EmbeddingProvider,'for_user',classmethod(embedding_config))
    monkeypatch.setattr(EmbeddingProvider,'embed',embedding)
    async def model_config(*args, **kwargs):
        return {'model_id':'test','base_url':'http://test/v1','api_key':'test','temperature':0}
    monkeypatch.setattr(LLMService,'get_model_config',model_config)
    headers=auth(uid)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        imported=await client.post('/api/data-sources/import',headers=headers,data={'name':'订单'},files={'file':('orders.csv',CSV,'text/csv')})
        assert imported.status_code==200, imported.text
        sid=imported.json()['id']
        uploaded=await client.post(f'/api/knowledge/bases/{kb_id}/documents/upload',headers=headers,
            files={'file':('policy.md','# 华东折扣政策\n\n折扣为 5%，需主管审批；审批规则适用于华东客户。'.encode(),'text/markdown')})
        assert uploaded.status_code==200, uploaded.text
        async with AsyncSessionLocal() as db:
            job=await db.scalar(select(IngestionJob).where(IngestionJob.doc_id==uploaded.json()['id']))
            job_id,chunk_id=job.id,job.version+'_0'
        await ingest(job_id)
        script=[('list_available_resources',{}),('get_business_schema',{'source_id':sid}),
            ('execute_readonly_sql',{'source_id':sid,'sql':"SELECT SUM(amount) AS total FROM dataset WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-02-01'"}),
            ('search_knowledge',{'query':'华东客户折扣政策'}),('search_knowledge',{'query':'折扣主管审批规则'}),
            ('read_document_section',{'chunk_id':chunk_id})]
        def response(messages, **kwargs):
            count=sum(1 for m in messages if m.role=='tool')
            if count<len(script):
                name,arguments=script[count]
                return ChatMessage(role='assistant',blocks=[ToolCallBlock(tool_name=name,tool_call_id=f'flow{count}',tool_kwargs=arguments)])
            return ChatMessage(role='assistant',content=delivery('一月销售额为 0.30 [查询 Q1]。华东折扣需主管审批 [来源 S1]。'))
        llm=MockFunctionCallingLLM(response_generator=response,is_chat_model=True)
        monkeypatch.setattr('app.agents.executor.OpenAILike',lambda **kwargs:llm)
        wid = await workspace(client, headers, [kb_id], [sid])
        r=await client.post('/api/chat/stream',headers=headers,json={'query':'汇总一月销售额，检索折扣政策及审批规则','workspace_id':wid})
        events=read_events(r)
        assert events[-1]['status']=='completed',events
        assert [e['name'] for e in events if e['type']=='tool_start']==[name for name,_ in script]
        rows=next(e for e in events if e['type']=='query_result')['rows']
        assert rows==[{'total':'0.30'}]
        citation=next(e for e in reversed(events) if e['type']=='citations')['items'][0]
        assert '主管审批' in citation['content'] and citation['headings']==['华东折扣政策']
        assert citation['chunk_id']==chunk_id


@pytest.mark.parametrize('chart_word, expected_type', [('折线图', 'line'), ('饼图', 'pie'), ('环形图', 'pie'), ('柱状图', 'bar'), ('列出月份和金额', None), ('不要图表，只用表格', None)])
@pytest.mark.asyncio
async def test_explicit_chart_intent_survives_stream_and_message_storage(monkeypatch, chart_word, expected_type):
    """User wording must control the emitted and persisted chart, independent of LLM SQL arguments."""
    from app.models.conversation import Message as SavedMessage
    from test_platform import seed, auth
    from test_tabular import CSV

    uid, _, _ = await seed()
    async def config(*args, **kwargs):
        return {'model_id': 'test', 'base_url': 'http://test/v1', 'api_key': 'test', 'temperature': 0}
    monkeypatch.setattr(LLMService, 'get_model_config', config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        imported = await client.post('/api/data-sources/import', headers=auth(uid), data={'name': '月度销售'},
                                    files={'file': ('orders.csv', CSV, 'text/csv')})
        assert imported.status_code == 200, imported.text
        sid = imported.json()['id']
        script = [('get_business_schema', {'source_id': sid}), ('execute_readonly_sql', {
            'source_id': sid, 'sql': "SELECT SUBSTRING(CAST(order_date AS VARCHAR), 1, 7) AS month, SUM(amount) AS revenue FROM dataset GROUP BY month ORDER BY month"})]
        def response(messages, **kwargs):
            count = sum(1 for m in messages if m.role == 'tool')
            if count < len(script):
                name, arguments = script[count]
                return ChatMessage(role='assistant', blocks=[ToolCallBlock(tool_name=name, tool_call_id=f'chart{count}', tool_kwargs=arguments)])
            return ChatMessage(role='assistant', content=delivery('已汇总各月销售收入 [查询 Q1]。'))
        llm = MockFunctionCallingLLM(response_generator=response, is_chat_model=True)
        monkeypatch.setattr('app.agents.executor.OpenAILike', lambda **kwargs: llm)
        wid = await workspace(client, auth(uid), source_ids=[sid])
        result = await client.post('/api/chat/stream', headers=auth(uid), json={
            'query': f'按月份汇总销售收入，用{chart_word}展示 2024 年至 2026 年 10 月 9 日的变化', 'workspace_id': wid})
        assert result.status_code == 200, result.text
        events = read_events(result)
        assert events[-1]['status'] == 'completed', [e.get('result') for e in events if e['type'] == 'tool_end']
        charts = [event['chart'] for event in events if event['type'] == 'tool_call' and event.get('chart')]
        if expected_type is None:
            assert charts == []
        else:
            assert len(charts) == 1
            assert charts[0]['type'] == expected_type
            assert charts[0]['data'] == [{'month': '2026-01', 'revenue': 0.3}, {'month': '2026-02', 'revenue': 100.0}]
        conversation_id = next(e['conversation_id'] for e in events if e['type'] == 'run_started')
    async with AsyncSessionLocal() as db:
        message = await db.scalar(select(SavedMessage).where(SavedMessage.conversation_id == conversation_id, SavedMessage.role == 'assistant'))
        stored_chart = json.loads(message.tool_calls).get('chart')
        if expected_type is None:
            assert stored_chart is None
        else:
            assert stored_chart['type'] == expected_type


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
    charts = [event['chart'] for event in events if event['type'] == 'tool_call' and event.get('chart')]
    assert [chart['type'] for chart in charts] == ([expected] if expected else [])
