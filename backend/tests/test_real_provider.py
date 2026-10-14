"""Opt-in acceptance against the user's configured provider; fixtures contain no business secrets."""
import os
import json
import asyncio
from pathlib import Path
import pytest
import httpx
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.platform import IngestionJob,AgentRun
from app.models.knowledge import Document
from app.services.llm_service import LLMService
from app.ingestion.pipeline import ingest
from test_platform import seed,auth
from test_tabular import CSV
from agent_helpers import chat_input,read_events,presentation
from main import app

@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('RAG_REAL_PROVIDER_FILE'),reason='Requires an explicitly supplied private provider configuration')
async def test_real_provider_sql_document_joint_and_followup(monkeypatch,tmp_path):
    providers=json.loads(Path(os.environ['RAG_REAL_PROVIDER_FILE']).read_text())
    uid,_,kb=await seed()
    async def config(db,user_id,model_id=None,kind='llm'):
        assert user_id==uid
        return providers[kind]
    monkeypatch.setattr(LLMService,'get_model_config',config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=auth(uid)) as client:
        imported=await client.post('/api/data-sources/import',data={'name':'验收订单'},files={'file':('orders.csv',CSV,'text/csv')});assert imported.status_code==200
        sid=imported.json()['id']
        uploaded=await client.post(f'/api/knowledge/bases/{kb}/documents/upload',files={'file':('acceptance-policy.md','# 华东折扣政策\n\n华东客户折扣为5%，必须经主管审批。此文档仅用于重构验收。'.encode(),'text/markdown')});assert uploaded.status_code==200
        async with AsyncSessionLocal() as db:
            job=await db.scalar(select(IngestionJob).where(IngestionJob.doc_id==uploaded.json()['id']));job_id=job.id
        await ingest(job_id)
        async with AsyncSessionLocal() as db:
            doc=await db.get(Document,uploaded.json()['id']);assert doc.status=='ready',doc.error_msg
        ws=(await client.post('/api/workspaces',json={'name':'真实模型验收','kb_ids':[kb],'source_ids':[sid]})).json()['id']
        from app.workers.local import run_agent_worker
        worker=asyncio.create_task(run_agent_worker())
        report=[]
        try:
            thread=None
            questions=[
                ('查询2026年1月订单销售额，按订单日期筛选，保留原始金额精度。请用表格展示结果。','sql'),
                ('检索并引用华东客户折扣政策，说明折扣和审批要求。','document'),
                ('结合刚才的销售额和折扣政策说明业务事实与政策依据，分别引用，不要推断因果。然后按月份查询销售额并用折线图展示。','joint'),
                ('沿用2026年1月的筛选条件，查询订单数量并用表格展示。','followup'),
            ]
            for question,kind in questions:
                payload=chat_input(question,ws,thread)
                response=await client.post('/api/chat/stream',json=payload)
                assert response.status_code==200,response.text
                events=read_events(response)
                assert events[-1]['type']=='RUN_FINISHED',f'{kind}: {events[-1]}'
                assert events[-1].get('outcome',{}).get('type','success')=='success'
                data=presentation(events)
                assert len(data['answer']['suggestions'])==3
                text='\n'.join(e.get('delta','') for e in events if e['type']=='TEXT_MESSAGE_CONTENT')
                assert '```' not in text and 'xychart-beta' not in text and 'matplotlib' not in text.lower()
                if kind=='sql':assert any(any(str(v) in {'0.30','0.3'} for row in q['rows'] for v in row.values()) for q in data['queries'])
                if kind=='document':assert data['citations'] and '主管审批' in text
                if kind=='joint':assert any(q.get('chart',{}).get('type')=='line' for q in data['queries'] if q.get('chart'))
                if kind=='followup':assert any(any(str(v)=='2' for row in q['rows'] for v in row.values()) for q in data['queries'])
                thread=payload['threadId']
                report.append({'case':kind,'text':text,'suggestions':data['answer']['suggestions'],
                    'queries':data['queries'],'citations':data['citations']})
        finally:
            worker.cancel();await asyncio.gather(worker,return_exceptions=True)
        target=os.environ.get('RAG_REAL_REPORT_FILE')
        if target:Path(target).write_text(json.dumps(report,ensure_ascii=False,indent=2))

@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('RAG_REAL_PROVIDER_FILE'),reason='Requires an explicitly supplied private provider configuration')
async def test_real_provider_sql_only(monkeypatch):
    providers=json.loads(Path(os.environ['RAG_REAL_PROVIDER_FILE']).read_text())
    uid,_,_=await seed()
    async def config(*args,**kwargs):return providers['llm']
    monkeypatch.setattr(LLMService,'get_model_config',config)
    from app.workers.local import run_agent_worker
    worker=asyncio.create_task(run_agent_worker())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=auth(uid)) as client:
            imported=await client.post('/api/data-sources/import',data={'name':'验收订单'},files={'file':('orders.csv',CSV,'text/csv')});sid=imported.json()['id']
            ws=(await client.post('/api/workspaces',json={'name':'SQL验收','source_ids':[sid]})).json()['id']
            payload=chat_input('按月汇总订单销售额，用折线图和表格展示。必须读取实际数据，不要输出绘图代码。',ws)
            response=await client.post('/api/chat/stream',json=payload)
            events=read_events(response)
            assert events[-1]['type']=='RUN_FINISHED',events[-1]
            data=presentation(events)
            assert len(data['answer']['suggestions'])==3
            assert any(query.get('chart',{}).get('type')=='line' for query in data['queries'] if query.get('chart'))
            assert any(any(str(value) in {'0.30','0.3'} for row in query['rows'] for value in row.values()) for query in data['queries'])
            text='\n'.join(e.get('delta','') for e in events if e['type']=='TEXT_MESSAGE_CONTENT')
            assert '```' not in text and 'xychart' not in text
            if os.environ.get('RAG_REAL_REPORT_FILE'):
                Path(os.environ['RAG_REAL_REPORT_FILE']+'.sql.json').write_text(json.dumps({'text':text,'data':data},ensure_ascii=False,indent=2))
    finally:
        worker.cancel();await asyncio.gather(worker,return_exceptions=True)
