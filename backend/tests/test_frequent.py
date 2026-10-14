"""Lifecycle tests use deterministic model substitutes, not semantic-quality claims."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select, func, delete
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.conversation import Conversation, Message, BusinessWorkspace
from app.models.frequent import QuestionGroup, QuestionRecord
from app.models.knowledge import KnowledgeBase
from app.models.platform import DataSource
from app.services import frequent_service as svc
from app.infrastructure.embeddings import EmbeddingProvider
from app.services.llm_service import LLMService
from app.workers.frequent import process, recover, pending_ids
from app.security.auth import create_access_token
from app.application.chat import prepare_chat
from app.schemas.chat import ChatRequest
from main import app

@pytest.fixture
def providers(monkeypatch):
    calls = {'embed':0, 'judge':0, 'candidates':[]}
    async def for_user(cls, db, user):
        return cls({'base_url':'http://test/v1', 'model_id':'embed', 'api_key':'unused'})
    async def embed(self, texts, **kwargs):
        calls['embed'] += 1
        return [[1., 0.] for _ in texts]
    async def cfg(*args, **kwargs):
        return {'model_id':'llm', 'api_key':'unused', 'base_url':'http://test/v1'}
    async def judge(cfg, question, asked_at, candidates):
        calls['judge'] += 1; calls['candidates'].append(candidates)
        return True, candidates[0].id if candidates else None
    monkeypatch.setattr(EmbeddingProvider, 'for_user', classmethod(for_user))
    monkeypatch.setattr(EmbeddingProvider, 'embed', embed)
    monkeypatch.setattr(LLMService, 'get_model_config', cfg)
    monkeypatch.setattr(svc, 'judge', judge)
    return calls

async def seed():
    async with AsyncSessionLocal() as db:
        a, b = User(username='a', hashed_password='unused'), User(username='b', hashed_password='unused')
        db.add_all([a,b]); await db.flush()
        conv = Conversation(user_id=a.id)
        kb = KnowledgeBase(user_id=a.id, name='kb')
        source = DataSource(user_id=a.id, name='source', connection_secret='unused')
        db.add_all([conv,kb,source]); await db.commit()
        return a.id,b.id,conv.id,kb.id,source.id

async def message(user, conv, text='2026年北京代表处收入是多少？', kbs=(), sources=()):
    async with AsyncSessionLocal() as db:
        msg = Message(user_id=user, conversation_id=conv, role='user', content=text)
        db.add(msg)
        await svc.enqueue(db,msg,kbs,sources); await svc.enqueue(db,msg,kbs,sources)
        await db.commit()
        return msg.id

def auth(user):
    return {'Authorization':'Bearer '+create_access_token({'sub':user})}

def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')

@pytest.mark.asyncio
async def test_exact_count_api_delete_and_idempotence(providers):
    a,b,conv,kb,source = await seed()
    ids = [await message(a,conv) for _ in range(3)]
    for mid in ids: await process(mid); await process(mid)
    assert providers['embed'] == providers['judge'] == 1
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(QuestionRecord)) == 3
        assert await db.scalar(select(func.count()).select_from(QuestionGroup)) == 1
    async with client() as c:
        listed = (await c.get('/api/frequent-questions',headers=auth(a))).json()
        assert len(listed) == 1 and listed[0]['count'] == 3
        assert datetime.fromisoformat(listed[0]['last_asked_at']).utcoffset().total_seconds() == 0
        assert (await c.get('/api/frequent-questions',headers=auth(b))).json() == []
        assert (await c.get('/api/frequent-questions',params={'kb_ids':kb},headers=auth(a))).json() == []
        assert (await c.get('/api/frequent-questions',params={'source_ids':source},headers=auth(b))).json() == []
        assert (await c.get('/api/frequent-questions')).status_code == 401
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Message).where(Message.id == ids[0])); await db.commit()
        assert (await c.get('/api/frequent-questions',headers=auth(a))).json() == []
        assert (await c.put('/api/settings/app-config/frequent_questions',headers=auth(a),json={'config_value':{'threshold':2}})).status_code == 200
        assert (await c.get('/api/frequent-questions',headers=auth(a))).json()[0]['count'] == 2
        assert (await c.delete(f'/api/sessions/{conv}',headers=auth(a))).status_code == 200
        assert (await c.get('/api/frequent-questions',headers=auth(a))).json() == []
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(QuestionRecord)) == 0

@pytest.mark.asyncio
async def test_scope_isolation_and_canonicalization(providers):
    a,b,conv,kb,source = await seed()
    assert svc.scope_key([kb,kb],[source]) == svc.scope_key([kb],[source,source])
    assert svc.scope_key([kb],[]) != svc.scope_key([],[kb])
    for kbs,sources in [([],[]),([kb],[]),([kb],[source])]:
        await process(await message(a,conv,kbs=kbs,sources=sources))
        assert providers['candidates'][-1] == []
    async with AsyncSessionLocal() as db:
        other = Conversation(user_id=b); db.add(other); await db.commit(); other_id=other.id
    await process(await message(b,other_id))
    assert providers['candidates'][-1] == []
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(QuestionGroup)) == 4
        await db.execute(delete(User).where(User.id==b)); await db.commit()
        assert await db.scalar(select(func.count()).select_from(QuestionGroup)) == 3

@pytest.mark.asyncio
async def test_chat_enqueues_same_transaction(providers):
    a,_,conv,kb,source=await seed()
    async with AsyncSessionLocal() as db:
        space = BusinessWorkspace(user_id=a,name='测试',kb_ids=json.dumps([kb]),source_ids=json.dumps([source]))
        db.add(space); await db.flush()
        (await db.get(Conversation,conv)).workspace_id=space.id
        await db.commit()
        await prepare_chat(db,a,ChatRequest(query='2026北京收入',conversation_id=conv))
    async with AsyncSessionLocal() as db:
        record=await db.scalar(select(QuestionRecord))
        assert record.status=='pending' and record.kb_ids==[kb] and record.source_ids==[source]
        assert (await db.get(Message,record.message_id)).content=='2026北京收入'
        msg=Message(user_id=a,conversation_id=conv,role='user',content='rollback')
        db.add(msg); await svc.enqueue(db,msg,[],[]); mid=msg.id; await db.rollback()
    assert providers['embed']==providers['judge']==0
    async with AsyncSessionLocal() as db:
        assert await db.get(Message,mid) is None and await db.get(QuestionRecord,mid) is None

@pytest.mark.asyncio
async def test_paraphrase_top_three_relative_and_eligibility(providers,monkeypatch):
    a,_,conv,_,_=await seed()
    await process(await message(a,conv))
    await process(await message(a,conv,'北京代表处2026年确认了多少收入？'))
    assert len(providers['candidates'][-1])==1
    for _ in range(2): await process(await message(a,conv,'今年北京收入是多少？'))
    assert providers['judge']==4
    async def ineligible(*args): return False,None
    monkeypatch.setattr(svc,'judge',ineligible)
    mid=await message(a,conv,'那上海呢'); await process(mid)
    async with AsyncSessionLocal() as db: assert (await db.get(QuestionRecord,mid)).status=='skipped'
    async def new_group(*args): return True,None
    monkeypatch.setattr(svc,'judge',new_group)
    for index in range(5): await process(await message(a,conv,f'产品型号{index}销售额'))
    async def top_three(cfg,question,asked,candidates):
        assert len(candidates)==3
        return True,None
    monkeypatch.setattr(svc,'judge',top_three)
    await process(await message(a,conv,'独立新需求'))

@pytest.mark.asyncio
async def test_retry_recovery_failure_deleted_resource(providers,monkeypatch):
    a,_,conv,kb,_=await seed()
    async def timeout(*args): raise TimeoutError('secret must not persist')
    monkeypatch.setattr(svc,'judge',timeout)
    mid=await message(a,conv)
    for _ in range(4): await process(mid)
    async with AsyncSessionLocal() as db:
        r=await db.get(QuestionRecord,mid)
        assert (r.status,r.attempts,r.error_code)==('failed',3,'TimeoutError')
        assert await db.scalar(select(func.count()).select_from(QuestionGroup))==0
    abandoned=await message(a,conv)
    async with AsyncSessionLocal() as db:
        r=await db.get(QuestionRecord,abandoned); r.status='processing'; r.attempts=1; await db.commit()
    await recover()
    async with AsyncSessionLocal() as db: assert (await db.get(QuestionRecord,abandoned)).status=='pending'
    invalid=await message(a,conv,kbs=[kb])
    async with AsyncSessionLocal() as db:
        await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id==kb)); await db.commit()
    await process(invalid)
    async with AsyncSessionLocal() as db: assert (await db.get(QuestionRecord,invalid)).status=='skipped'

@pytest.mark.asyncio
async def test_disable_inflight_reenable_no_backfill(providers,monkeypatch):
    a,_,conv,_,_=await seed(); mid=await message(a,conv)
    started,finish=asyncio.Event(),asyncio.Event()
    async def blocked(*args):
        started.set(); await finish.wait(); return True,None
    monkeypatch.setattr(svc,'judge',blocked)
    task=asyncio.create_task(process(mid)); await asyncio.wait_for(started.wait(),5)
    async with client() as c:
        await c.put('/api/settings/app-config/frequent_questions',headers=auth(a),json={'is_enabled':False})
        off=await message(a,conv)
        await c.put('/api/settings/app-config/frequent_questions',headers=auth(a),json={'is_enabled':True})
    finish.set(); await task
    async with AsyncSessionLocal() as db:
        assert (await db.get(QuestionRecord,mid)).status=='skipped'
        assert await db.get(QuestionRecord,off) is None
        assert await db.scalar(select(func.count()).select_from(QuestionGroup))==0

@pytest.mark.asyncio
async def test_profile_change_pause_reset_preserves_chat(providers,monkeypatch):
    a,_,conv,_,_=await seed(); await process(await message(a,conv))
    async def changed(cls,db,user): return cls({'base_url':'http://test/v1','model_id':'different','api_key':'unused'})
    monkeypatch.setattr(EmbeddingProvider,'for_user',classmethod(changed))
    mid=await message(a,conv); await process(mid)
    later=await message(a,conv,'其他问题'); await process(later)
    assert await pending_ids()==[]
    async with AsyncSessionLocal() as db:
        r=await db.get(QuestionRecord,mid)
        assert (r.status,r.error_code,r.attempts)==('pending',svc.PROFILE_CHANGED,0)
        assert (await db.get(QuestionRecord,later)).attempts==0
    async with client() as c:
        assert (await c.get('/api/settings/app-config',headers=auth(a))).json()['frequent_questions']['reset_required']
        assert (await c.delete('/api/frequent-questions',headers=auth(a))).status_code==200
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Message))==3
        assert await db.scalar(select(func.count()).select_from(QuestionRecord))==0
    await process(await message(a,conv))
    async with AsyncSessionLocal() as db: assert await db.scalar(select(func.count()).select_from(QuestionGroup))==1

@pytest.mark.parametrize('threshold',[0,-1,1.5,True,'3'])
@pytest.mark.asyncio
async def test_invalid_threshold_rejected(threshold):
    a,*_=await seed()
    async with client() as c:
        r=await c.put('/api/settings/app-config/frequent_questions',headers=auth(a),json={'config_value':{'threshold':threshold}})
        assert r.status_code==422

@pytest.mark.parametrize('raw',['{}','null','{"eligible":"true","matched_group_id":null}',
    '{"eligible":true,"matched_group_id":"foreign"}','{"eligible":false,"matched_group_id":"g"}',
    '```json\n{"eligible":true,"matched_group_id":null}\n```'])
def test_bad_model_output_rejected(raw):
    with pytest.raises(ValueError): svc.parse_decision(raw,[SimpleNamespace(id='g')])

def test_normalization_and_time():
    assert svc.normalize('  收入  高于\n3000 万  ')=='收入 高于 3000 万'
    assert svc.normalize('X-100 不低于3.5万元')=='X-100 不低于3.5万元'
    for text in ['今年收入','本月收入','昨天收入','近三个月','过去七天','上个月','本季度','最近','两年前收入','三天后销售额','this year']:
        assert svc.RELATIVE_TIME.search(text)
    assert svc.local_time(datetime(2025,12,31,16))=='2026-01-01T00:00:00+08:00'

@pytest.mark.asyncio
async def test_bad_group_retries_without_partial_group(providers,monkeypatch):
    a,_,conv,_,_=await seed()
    async def bad(*args): return True,'foreign-group'
    monkeypatch.setattr(svc,'judge',bad)
    mid=await message(a,conv)
    for _ in range(3): await process(mid)
    async with AsyncSessionLocal() as db:
        r=await db.get(QuestionRecord,mid)
        assert r.status=='failed' and r.attempts==3 and r.group_id is None
        assert await db.scalar(select(func.count()).select_from(QuestionGroup))==0

@pytest.mark.asyncio
async def test_list_limit_sort_and_first_representative_survives_deletion(providers,monkeypatch):
    a,_,conv,_,_=await seed()
    original=await message(a,conv); await process(original)
    paraphrase=await message(a,conv,'北京代表处2026年确认了多少收入？'); await process(paraphrase)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Message).where(Message.id==original)); await db.commit()
        group=await db.scalar(select(QuestionGroup))
        assert group.representative_question=='2026年北京代表处收入是多少？'
    async def new(*args): return True,None
    monkeypatch.setattr(svc,'judge',new)
    for i in range(12): await process(await message(a,conv,f'产品{i}销售额'))
    async with client() as c:
        await c.put('/api/settings/app-config/frequent_questions',headers=auth(a),json={'config_value':{'threshold':1}})
        rows=(await c.get('/api/frequent-questions',headers=auth(a))).json()
        assert len(rows)==10 and rows[0]['question']=='产品11销售额'
        assert rows[-1]['question']=='产品2销售额'
    # Adding a member to the old group changes count ordering without changing representative.
    monkeypatch.setattr(svc,'judge',lambda *args: None)  # exact path must avoid LLM
    await process(await message(a,conv,'北京代表处2026年确认了多少收入？'))
    async with AsyncSessionLocal() as db:
        rows=await svc.list_questions(db,a,[],[])
        assert rows[0]['count']==2 and rows[0]['question']=='2026年北京代表处收入是多少？'

@pytest.mark.asyncio
async def test_reset_during_model_call_does_not_recreate_groups(providers,monkeypatch):
    a,_,conv,_,_=await seed(); mid=await message(a,conv)
    started,finish=asyncio.Event(),asyncio.Event()
    async def blocked(*args):
        started.set(); await finish.wait(); return True,None
    monkeypatch.setattr(svc,'judge',blocked)
    task=asyncio.create_task(process(mid)); await asyncio.wait_for(started.wait(),5)
    async with client() as c: await c.delete('/api/frequent-questions',headers=auth(a))
    finish.set(); await task
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(QuestionGroup))==0
        assert await db.get(Message,mid) is not None

@pytest.mark.asyncio
async def test_single_worker_lock(providers):
    import fcntl
    from app.config import settings
    from app.workers.frequent import run
    settings.STORAGE_DIR.mkdir(parents=True,exist_ok=True)
    with (settings.STORAGE_DIR/'frequent-worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(RuntimeError,match='单实例'): await run()

@pytest.mark.asyncio
async def test_judge_requests_json_and_keeps_eligible_unmatched(monkeypatch):
    from openai import AsyncOpenAI
    import json
    def respond(request):
        body=json.loads(request.content)
        assert body['response_format']=={'type':'json_object'}
        data=json.loads(body['messages'][1]['content'])
        assert data['question']=='2025年北京收入是多少？'
        assert data['candidates'][0]['id']=='candidate'
        assert data['asked_at']=='2026-10-12T12:00:00+08:00'
        assert data['time_context']=={'year':2026,'month':10,'local_date':'2026-10-12','yesterday':'2026-10-11'}
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':0,'model':'test',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'{"eligible":true,"matched_group_id":null}'}}]})
    def client(**kwargs):
        return AsyncOpenAI(**kwargs,http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(svc,'AsyncOpenAI',client)
    eligible,matched=await svc.judge({'model_id':'test','api_key':'unused','base_url':'http://test/v1'},
        '2025年北京收入是多少？',datetime(2026,10,12,4),[SimpleNamespace(id='candidate',
        representative_question='2026年北京收入是多少？',representative_asked_at=datetime(2026,10,12,3))])
    assert eligible and matched is None


def test_relative_time_context_uses_each_questions_own_shanghai_date():
    assert svc.time_context(datetime(2026,12,31,16)) == {
        'year':2027, 'month':1, 'local_date':'2027-01-01', 'yesterday':'2026-12-31'}
    assert svc.time_context(datetime(2026,12,31,0))['year'] == 2026
