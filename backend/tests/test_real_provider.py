"""Opt-in acceptance against the user's configured provider; fixtures contain no business secrets."""
import os
import json
import asyncio
from pathlib import Path
import pytest
import httpx
from app.services.llm_service import LLMService
from test_platform import seed, auth
from test_tabular import CSV
from agent_helpers import chat_input, read_events, presentation
from main import app

@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('RAG_REAL_PROVIDER_FILE'), reason='Requires an explicitly supplied private provider configuration')
async def test_real_provider_sql_only(monkeypatch):
    providers = json.loads(Path(os.environ['RAG_REAL_PROVIDER_FILE']).read_text())
    uid, _ = await seed()
    async def config(*args, **kwargs):
        return providers['llm']
    monkeypatch.setattr(LLMService, 'get_model_config', config)
    from app.workers.local import run_agent_worker
    worker = asyncio.create_task(run_agent_worker())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth(uid)) as client:
            imported = await client.post('/api/data-sources/import', data={'name': '验收订单'}, files={'file': ('orders.csv', CSV, 'text/csv')})
            sid = imported.json()['id']
            ws = (await client.post('/api/workspaces', json={'name': 'SQL验收', 'source_ids': [sid]})).json()['id']
            payload = chat_input('按月汇总订单销售额，用折线图和表格展示。必须读取实际数据，不要输出绘图代码。', ws)
            response = await client.post('/api/chat/stream', json=payload)
            events = read_events(response)
            assert events[-1]['type'] == 'RUN_FINISHED', events[-1]
            data = presentation(events)
            assert len(data['answer']['suggestions']) == 3
            assert any(query.get('chart', {}).get('type') == 'line' for query in data['queries'] if query.get('chart'))
            assert any(any(str(value) in {'0.30', '0.3'} for row in query['rows'] for value in row.values()) for query in data['queries'])
            text = '\n'.join(e.get('delta', '') for e in events if e['type'] == 'TEXT_MESSAGE_CONTENT')
            assert '```' not in text and 'xychart' not in text
            if os.environ.get('RAG_REAL_REPORT_FILE'):
                Path(os.environ['RAG_REAL_REPORT_FILE'] + '.sql.json').write_text(json.dumps({'text': text, 'data': data}, ensure_ascii=False, indent=2))
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
