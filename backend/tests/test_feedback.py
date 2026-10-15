import asyncio
import json
import uuid
from datetime import datetime, timedelta
import httpx
import pytest
from sqlalchemy import select, func, delete, update
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.conversation import Conversation, Message, BusinessWorkspace
from app.models.platform import AgentRun
from app.models.feedback import AnswerFeedback, AnswerFeedbackEvent
from app.security.auth import create_access_token
from main import app


def auth(uid):
    return {'Authorization':'Bearer ' + create_access_token({'sub':uid})}


async def seed(status='completed'):
    async with AsyncSessionLocal() as db:
        a=User(username='张经理',hashed_password='unused')
        b=User(username='李经理',hashed_password='unused')
        admin=User(username='核查员',hashed_password='unused',role='feedback_admin')
        db.add_all([a,b,admin]);await db.flush()
        workspace=BusinessWorkspace(user_id=a.id,name='经营分析')
        db.add(workspace);await db.flush()
        conv=Conversation(user_id=a.id,workspace_id=workspace.id)
        db.add(conv);await db.flush()
        question=Message(user_id=a.id,conversation_id=conv.id,role='user',content='本月应收账款账龄 30%_？',created_at=datetime.utcnow()-timedelta(seconds=2))
        answer=Message(user_id=a.id,conversation_id=conv.id,role='assistant',content='本月应收账款主要集中在 30–60 天。')
        db.add_all([question,answer]);await db.flush()
        run=None
        run=AgentRun(user_id=a.id,conversation_id=conv.id,workspace_id=workspace.id,assistant_message_id=answer.id,status=status,model='test-model',
            input_payload={'user_message_id':question.id,'memory':'DO-NOT-COPY','api_key':'DO-NOT-COPY'},resource_scope={'source_ids':[]})
        db.add(run);await db.flush()
        answer.tool_calls=json.dumps({'run_id':run.id,'status':status,'api_key':'DO-NOT-COPY','execution_events':[{'message':'DO-NOT-COPY'}],
            'presentation':{'answer':{'version':1,'sections':[{'title':'账龄','summary':'主要集中在 30–60 天。'}],'suggestions':[]},'queries':[{'query_id':'q1','citation_id':'Q1','rows':[{'amount':1200}],'sql':'SELECT amount FROM aging','truncated':True,'parameters':{},'connection_secret':'DO-NOT-COPY'}]}})
        await db.commit()
        return a.id,b.id,admin.id,conv.id,question.id,answer.id,run.id if run else None


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')


@pytest.mark.asyncio
async def test_full_review_loop_and_private_responses():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        created=await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error','comment':'请核查金额'})
        assert created.status_code==201,created.text
        fid=created.json()['id']
        assert 'evidence' not in created.text and 'processing_note' not in created.text
        duplicate=await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'other','comment':'另一条'})
        assert duplicate.status_code==200 and duplicate.json()['deduplicated']
        listing=(await cli.get('/api/feedback',headers=auth(a))).json()
        assert listing['total']==1 and listing['items'][0]['question']=='本月应收账款账龄 30%_？'
        assert 'evidence_snapshot' not in listing['items'][0]
        detail=(await cli.get(f'/api/feedback/{fid}',headers=auth(a))).json()
        assert detail['user_comment']=='请核查金额'
        assert detail['evidence_snapshot']['context']['question_message_id']==q
        assert 'DO-NOT-COPY' not in json.dumps(detail)
        assert detail['evidence_snapshot']['schema_version']==2
        assert detail['evidence_snapshot']['presentation']['queries'][0]['truncated'] is True
        assert detail['created_at'].endswith('Z')
        invalid=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'resolved','processing_note':'  ','expected_version':1})
        assert invalid.status_code==422
        saved=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'resolved','processing_note':'已核实，登记修复任务','expected_version':1})
        assert saved.status_code==200,saved.text
        assert saved.json()['version']==2 and len(saved.json()['history'])==2
        stale=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'pending','processing_note':'重新打开','expected_version':1})
        assert stale.status_code==409
        no_op=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'resolved','processing_note':'已核实，登记修复任务','expected_version':2})
        assert no_op.json()['version']==2 and len(no_op.json()['history'])==2
        invalid=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'pending','processing_note':'已核实，登记修复任务','expected_version':2})
        assert invalid.status_code==422
        reopened=await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'pending','processing_note':'回归仍有误，重新核查','expected_version':2})
        assert reopened.json()['history'][-1]['action']=='reopened'
        context=(await cli.get(f'/api/sessions/{c}/feedback-context',headers=auth(a))).json()
        assert context['items'][0]['feedback']['status']=='pending'
        assert 'processing_note' not in json.dumps(context)


@pytest.mark.asyncio
async def test_authorization_and_forged_fields():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(b),json={'reason':'data_error'})).status_code==404
        assert (await cli.post(f'/api/messages/{q}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==422
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error','reporter_id':b})).status_code==422
        fid=(await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).json()['id']
        for path in ['/api/feedback',f'/api/feedback/{fid}']:
            assert (await cli.get(path,headers=auth(a))).status_code==200
        assert (await cli.patch(f'/api/feedback/{fid}',headers=auth(a),json={'status':'resolved','processing_note':'越权','expected_version':1})).status_code==200
        assert (await cli.get(f'/api/sessions/{c}/feedback-context',headers=auth(b))).status_code==404
        assert (await cli.get(f'/api/sessions/{c}',headers=auth(admin))).status_code==404
        assert (await cli.get(f'/api/runs/{r}',headers=auth(admin))).status_code==404
        me=(await cli.get('/api/auth/me',headers=auth(admin))).json()
        assert me['role']=='feedback_admin'
        async with AsyncSessionLocal() as db:
            await db.execute(update(User).where(User.id==admin).values(role='user'));await db.commit()
        assert (await cli.get('/api/feedback',headers=auth(admin))).status_code==200


@pytest.mark.asyncio
async def test_filter_literal_characters_pagination_and_validation():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})
        async def total(**params):
            return (await cli.get('/api/feedback',headers=auth(a),params=params)).json()['total']
        assert await total(question='30%_')==1
        assert await total(question='30__')==0
        assert await total(user='张',status='pending')==1
        assert await total(user='李')==0
        assert await total(status='resolved')==0
        assert await total(question='  ')==1
        page=(await cli.get('/api/feedback',headers=auth(a),params={'page':2})).json()
        assert page['items']==[] and page['total']==1
        for params in [{'status':'invalid'},{'page':0},{'page_size':100},{'question':'x'*201}]:
            assert (await cli.get('/api/feedback',headers=auth(admin),params=params)).status_code==422


@pytest.mark.asyncio
@pytest.mark.parametrize('status',['queued','running','cancel_requested','failed','cancelled'])
async def test_ineligible_runs(status):
    a,b,admin,c,q,m,r=await seed(status=status)
    async with client() as cli:
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==422


@pytest.mark.asyncio
async def test_partial_run_uses_explicit_question_link():
    a,b,admin,c,q,m,r=await seed(status='partial')
    async with AsyncSessionLocal() as db:
        # An extra question after the original run must not replace its explicit input link.
        latest=Message(user_id=a,conversation_id=c,role='user',content='不能配到这个问题')
        db.add(latest);await db.commit()
    async with client() as cli:
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==201
    async with AsyncSessionLocal() as db:
        record=await db.scalar(select(AnswerFeedback))
        assert record.question_message_id==q


@pytest.mark.asyncio
async def test_unlinked_reply_rejected_and_evidence_limit(monkeypatch):
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AgentRun).where(AgentRun.id==r))
            await db.commit()
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==422
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User))
            await db.commit()
        a,b,admin,c,q,m,r=await seed()
        async with AsyncSessionLocal() as db:
            answer=await db.get(Message,m)
            calls=json.loads(answer.tool_calls)
            calls['presentation']['answer']['sections'][0]['summary']='扩大快照'
            answer.tool_calls=json.dumps(calls);await db.commit()
        from app.services import feedback_service
        monkeypatch.setattr(feedback_service,'MAX_EVIDENCE_BYTES',10)
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==413
        monkeypatch.setattr(feedback_service,'MAX_EVIDENCE_BYTES',2*1024*1024)
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'other','comment':' '})).status_code==422
        assert (await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).status_code==201


@pytest.mark.asyncio
async def test_parallel_duplicate_and_stale_update():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        results=await asyncio.gather(*[cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'}) for _ in range(4)])
        assert sorted(result.status_code for result in results)==[200,200,200,201]
        fid=results[0].json()['id']
        updates=await asyncio.gather(*[cli.patch(f'/api/feedback/{fid}',headers=auth(admin),json={'status':'resolved','processing_note':note,'expected_version':1}) for note in ['结论一','结论二']])
        assert sorted(result.status_code for result in updates)==[200,409]
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AnswerFeedback))==1
        assert await db.scalar(select(func.count()).select_from(AnswerFeedbackEvent))==2


@pytest.mark.asyncio
async def test_deletion_retains_evidence_and_deletes_reporter_data():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        fid=(await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).json()['id']
        assert (await cli.delete(f'/api/sessions/{c}',headers=auth(a))).status_code==200
        detail=(await cli.get(f'/api/feedback/{fid}',headers=auth(admin))).json()
        assert detail['original_deleted'] and detail['evidence_snapshot']['answer']['content']
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id==a));await db.commit()
            assert await db.scalar(select(func.count()).select_from(AnswerFeedback))==0
            assert await db.scalar(select(func.count()).select_from(AnswerFeedbackEvent))==0


@pytest.mark.asyncio
async def test_event_failure_rolls_back_review(monkeypatch):
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        fid=(await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).json()['id']
    from sqlalchemy import event
    def fail(*args):
        raise RuntimeError('audit unavailable')
    event.listen(AnswerFeedbackEvent,'before_insert',fail)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as cli:
            result=await cli.patch(f'/api/feedback/{fid}',headers=auth(admin),json={'status':'resolved','processing_note':'已核实','expected_version':1})
            assert result.status_code==500
    finally:
        event.remove(AnswerFeedbackEvent,'before_insert',fail)
    async with AsyncSessionLocal() as db:
        record=await db.get(AnswerFeedback,fid)
        assert record.status=='pending' and record.version==1 and record.processing_note==''


@pytest.mark.asyncio
async def test_snapshot_uses_original_run_scope_and_stays_immutable():
    a,b,admin,c,q,m,r=await seed()
    async with AsyncSessionLocal() as db:
        run=await db.get(AgentRun,r)
        run.resource_scope={'source_ids':['historical-source']}
        conv=await db.get(Conversation,c)
        conv.scope_version=2
        await db.commit()
    async with client() as cli:
        fid=(await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).json()['id']
        async with AsyncSessionLocal() as db:
            answer=await db.get(Message,m);answer.content='之后修改的正文';await db.commit()
        detail=(await cli.get(f'/api/feedback/{fid}',headers=auth(admin))).json()
        assert detail['evidence_snapshot']['resource']['source_ids']==['historical-source']
        assert detail['evidence_snapshot']['resource']['scope_version']==0
        assert detail['evidence_snapshot']['answer']['content']!='之后修改的正文'


@pytest.mark.asyncio
async def test_deleted_handler_keeps_review_attribution():
    a,b,admin,c,q,m,r=await seed()
    async with client() as cli:
        fid=(await cli.post(f'/api/messages/{m}/feedback',headers=auth(a),json={'reason':'data_error'})).json()['id']
        assert (await cli.patch(f'/api/feedback/{fid}',headers=auth(admin),json={'status':'resolved','processing_note':'已核查','expected_version':1})).status_code==200
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id==admin))
            await db.execute(update(User).where(User.id==b).values(role='feedback_admin'))
            await db.commit()
        detail=(await cli.get(f'/api/feedback/{fid}',headers=auth(b))).json()
        assert detail['last_handled_by'] is None
        assert detail['history'][-1]['actor_id'] is None
        assert detail['history'][-1]['actor_name']=='核查员'
