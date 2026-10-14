from agent_helpers import chat_input
import json
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation, Message
from app.models.knowledge import KnowledgeBase
from app.models.platform import AgentRun, DataSource
from app.models.memory import MemoryFact
from app.application.chat import prepare_chat
from app.schemas.chat import ChatRequest
from app.services.llm_service import LLMService
from test_platform import seed, auth
from main import app

@pytest.mark.asyncio
async def test_workspace_management_fixed_binding_and_isolation():
    a, b, kb = await seed()
    async with AsyncSessionLocal() as db:
        source = DataSource(user_id=a, name='销售', connection_secret='unused')
        db.add(source)
        await db.commit()
        sid = source.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth(a)) as client:
        defaults = (await client.get('/api/workspaces')).json()
        assert defaults[0]['status'] == 'empty'
        assert (await client.get('/api/workspaces')).json() == defaults
        space = (await client.post('/api/workspaces', json={'name': '销售分析', 'kb_ids': [kb], 'source_ids': [sid]})).json()
        wid = space['id']
        assert space['version'] == 1 and space['status'] == 'ready'
        first = (await client.post('/api/sessions', json={'workspace_id': wid})).json()
        assert first['workspace_id'] == wid
        for override in ({'kb_ids': []}, {'source_ids': []}, {'workspace_id': defaults[0]['id']}):
            assert (await client.put('/api/sessions/' + first['id'], json=override)).status_code == 422
        assert (await client.post('/api/sessions', json={'workspace_id': wid, 'kb_ids': []})).status_code == 422
        assert (await client.post('/api/chat/stream', json=chat_input(**{'query': '收入', 'workspace_id': wid, 'source_ids': []}))).status_code == 422
        renamed = (await client.put('/api/workspaces/' + wid, json={'name': '销售', 'kb_ids': [kb], 'source_ids': [sid], 'version': 1})).json()
        assert renamed['version'] == 1
        changed = (await client.put('/api/workspaces/' + wid, json={'name': '销售', 'source_ids': [sid], 'version': 1})).json()
        assert changed['version'] == 2
        assert (await client.put('/api/workspaces/' + wid, json={'name': '旧编辑', 'version': 1})).status_code == 409
        assert (await client.put('/api/workspaces/' + wid, headers=auth(b), json={'name': '窃取'})).status_code == 404
        assert (await client.post('/api/sessions', headers=auth(b), json={'workspace_id': wid})).status_code == 404
        assert (await client.post('/api/workspaces', headers=auth(b), json={'name': '窃取', 'kb_ids': [kb]})).status_code == 403
        assert (await client.post('/api/chat/stream', headers=auth(b), json=chat_input(**{'query': '收入', 'conversation_id': first['id']}))).status_code == 404
        async with AsyncSessionLocal() as db:
            await db.delete(await db.get(DataSource, sid))
            await db.commit()
        invalid = next((w for w in (await client.get('/api/workspaces')).json() if w['id'] == wid))
        assert invalid['status'] == 'invalid' and invalid['unavailable_source_ids'] == [sid]
        assert (await client.post('/api/chat/stream', json=chat_input(**{'query': '收入', 'conversation_id': first['id']}))).status_code == 403
        assert (await client.put('/api/workspaces/' + wid, json={'name': '修复', 'kb_ids': [kb], 'version': 2})).status_code == 200
        assert (await client.get('/api/sessions/' + first['id'])).json()['workspace_id'] == wid
        assert (await client.get('/api/frequent-questions', params={'workspace_id': wid})).status_code == 200
        assert (await client.get('/api/frequent-questions', headers=auth(b), params={'workspace_id': wid})).status_code == 404

@pytest.mark.asyncio
async def test_latest_scope_snapshot_context_boundary_and_empty_recovery(monkeypatch):
    a, _, kb = await seed()

    async def config(*args, **kwargs):
        return {'model_id': 'test'}
    monkeypatch.setattr(LLMService, 'get_model_config', config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth(a)) as client:
        space = (await client.post('/api/workspaces', json={'name': '政策', 'kb_ids': [kb]})).json()
        wid = space['id']
        async with AsyncSessionLocal() as db:
            request = ChatRequest(query='旧问题', workspace_id=wid)
            run = await prepare_chat(db, a, request)
            cid = run.conversation_id
            db.add(Message(user_id=a, conversation_id=cid, scope_version=1, role='assistant', content='旧范围回答'))
            db.add(MemoryFact(user_id=a, source_conversation_id=cid, raw_fact='旧范围业务事实'))
            kb2 = KnowledgeBase(user_id=a, name='新政策')
            db.add(kb2)
            await db.commit()
            kb2_id = kb2.id
            from app.application.chat import persist_run_event
            await persist_run_event(run.id, {'type':'RUN_FINISHED','threadId':cid,'runId':run.id})
            followup = ChatRequest(query='接着说', conversation_id=cid)
            pending_run = await prepare_chat(db, a, followup)
            memory=pending_run.input_payload['memory']
            assert 'history' not in pending_run.input_payload
            assert '旧范围业务事实' not in memory
        await client.put('/api/workspaces/' + wid, json={'name': '政策', 'kb_ids': [kb2_id], 'version': 1})
        captured = []

        class SnapshotExecutor:
            errors = 0
            citations = {}
            queries = []

            def __init__(self, uid, kbs, sources, cfg, **kwargs):
                captured.append((uid, kbs, sources))

            async def stream(self, query, **kwargs):
                yield {'type':'TEXT_MESSAGE_CONTENT','messageId':kwargs['assistant_message_id'],'delta':'旧执行完成'}
                yield {'type':'RUN_FINISHED','threadId':'t','runId':kwargs['run_id']}
        monkeypatch.setattr('app.application.chat.AgentExecutor', SnapshotExecutor)
        from app.application.chat import execute_agent_run

        async def no_memory(*args, **kwargs):
            pass
        monkeypatch.setattr('app.application.chat.MemoryService.extract_and_save_memory', no_memory)
        await execute_agent_run(pending_run.id)
        assert captured == [(a, [kb], [])]
        async with AsyncSessionLocal() as db:
            saved = await db.scalar(select(Message).where(Message.content == '旧执行完成'))
            assert saved.scope_version == 1
            request = ChatRequest(query='新问题', conversation_id=cid)
            newrun = await prepare_chat(db, a, request)
            history = newrun.input_payload.get('history', [])
            assert newrun.resource_scope['kb_ids'] == [kb2_id] and history == []
            assert newrun.scope_version == 2 and newrun.workspace_id == wid
            assert newrun.resource_scope == {'kb_ids': [kb2_id], 'source_ids': []}
            oldrun = await db.get(AgentRun, run.id)
            assert oldrun.scope_version == 1 and oldrun.resource_scope['kb_ids'] == [kb]
            assert (await db.scalar(select(Message).where(Message.content == '旧范围回答'))).content == '旧范围回答'
            with pytest.raises(HTTPException) as exc:
                await prepare_chat(db, a, ChatRequest(query='改绑', conversation_id=cid, workspace_id='another'))
            assert exc.value.status_code == 422
            newrun.status = 'cancelled'
            await db.commit()
        await client.put('/api/workspaces/' + wid, json={'name': '空范围', 'version': 2})
        blocked = await client.post('/api/chat/stream', json=chat_input(**{'query': '原问题', 'conversation_id': cid}))
        assert blocked.status_code == 422 and '管理页' in blocked.json()['detail']
        await client.put('/api/workspaces/' + wid, json={'name': '已修复', 'kb_ids': [kb], 'version': 3})
        async with AsyncSessionLocal() as db:
            recovered = await prepare_chat(db, a, ChatRequest(query='原问题', conversation_id=cid))
            assert 'history' not in recovered.input_payload
