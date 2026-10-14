import hashlib
import json
import uuid
import asyncio
import threading
import httpx
import pytest
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.config import settings
from app.models.knowledge import Document, KnowledgeBase
from app.models.platform import DocumentChunk, IngestionJob, MaintenanceJob
from app.infrastructure.embeddings import EmbeddingProvider
from app.infrastructure.vector_index import index
from app.infrastructure.storage import store
from app.ingestion.pipeline import ingest, write_vectors
from app.ingestion.maintenance import maintain, repair_index
from app.retrieval.retriever import KnowledgeRetriever
from main import app
from test_platform import seed, auth


@pytest.fixture
def providers(monkeypatch):
    selected = {'model': 'old'}
    async def for_user(cls, db, user_id):
        return cls({'base_url': 'http://test/v1', 'model_id': selected['model'], 'api_key': 'test-secret'})
    async def for_profile(cls, db, user_id, profile):
        for model in ('old', 'new'):
            provider = cls({'base_url': 'http://test/v1', 'model_id': model, 'api_key': 'test-secret'})
            if provider.profile == profile:
                return provider
        raise ValueError('missing model')
    async def embed(self, texts):
        return [[1., 0., 0.] for _ in texts]
    monkeypatch.setattr(EmbeddingProvider, 'for_user', classmethod(for_user))
    monkeypatch.setattr(EmbeddingProvider, 'for_profile', classmethod(for_profile))
    monkeypatch.setattr(EmbeddingProvider, 'embed', embed)
    return selected


async def upload(client, uid, kb, name='policy.txt'):
    response = await client.post(f'/api/knowledge/bases/{kb}/documents/upload', headers=auth(uid),
        files={'file': (name, '华东折扣政策：主管审批后折扣为百分之五。'.encode(), 'text/plain')})
    assert response.status_code == 200, response.text
    doc_id = response.json()['id']
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(IngestionJob).where(IngestionJob.doc_id == doc_id))
        job_id = job.id
    await ingest(job_id)
    return doc_id


@pytest.mark.asyncio
async def test_batch_switches_all_documents_and_cleans_only_old_versions(providers):
    uid, other, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        docs = [await upload(client, uid, kb, f'policy{i}.txt') for i in range(2)]
        async with AsyncSessionLocal() as db:
            old = {d.id: d.active_version for d in (await db.scalars(select(Document))).all()}
        providers['model'] = 'new'
        assert (await client.post(f'/api/knowledge/bases/{kb}/reindex', headers=auth(other))).status_code == 404
        response = await client.post(f'/api/knowledge/bases/{kb}/reindex', headers=auth(uid))
        assert response.status_code == 200, response.text
        batch = response.json()['batch_id']
        assert (await client.post(f'/api/knowledge/bases/{kb}/reindex', headers=auth(uid))).status_code == 409
        assert (await client.delete(f'/api/knowledge/documents/{docs[0]}', headers=auth(uid))).status_code == 409
        assert (await client.delete(f'/api/knowledge/bases/{kb}', headers=auth(uid))).status_code == 409
        async with AsyncSessionLocal() as db:
            jobs = list((await db.scalars(select(IngestionJob).where(IngestionJob.batch_id == batch))).all())
            assert all('test-secret' not in j.embedding_config for j in jobs)
        # The snapshot must continue using new even if the default changes again.
        providers['model'] = 'old'
        await ingest(jobs[0].id)
        async with AsyncSessionLocal() as db:
            assert {d.id:d.active_version for d in (await db.scalars(select(Document))).all()} == old
            assert (await db.get(IngestionJob, jobs[0].id)).status == 'staged'
        assert await KnowledgeRetriever(uid, [kb]).ainvoke('华东折扣')
        await ingest(jobs[1].id)
        async with AsyncSessionLocal() as db:
            assert (await db.get(KnowledgeBase, kb)).index_batch_id == ''
            assert all(d.active_version != old[d.id] and d.status == 'ready' for d in (await db.scalars(select(Document))).all())
            profile = EmbeddingProvider({'base_url':'http://test/v1','model_id':'new','api_key':'test-secret'}).profile
            assert set((await db.scalars(select(DocumentChunk.embedding_profile))).all()) == {profile}
            maintenance = list((await db.scalars(select(MaintenanceJob.id))).all())
        for job_id in maintenance:
            await maintain(job_id)
        old_profile = EmbeddingProvider({'base_url':'http://test/v1','model_id':'old','api_key':'test-secret'}).profile
        assert not index.ids(old_profile, 3, uid, kb, list(old.values()))
        assert await KnowledgeRetriever(uid, [kb]).ainvoke('华东折扣')


@pytest.mark.asyncio
async def test_batch_failure_preserves_entire_old_index_and_releases_lock(providers):
    uid, _, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        docs = [await upload(client, uid, kb, f'policy{i}.txt') for i in range(2)]
        async with AsyncSessionLocal() as db:
            old = {d.id:d.active_version for d in (await db.scalars(select(Document))).all()}
        providers['model'] = 'new'
        response = await client.post(f'/api/knowledge/bases/{kb}/reindex', headers=auth(uid))
        async with AsyncSessionLocal() as db:
            jobs = list((await db.scalars(select(IngestionJob).where(IngestionJob.batch_id == response.json()['batch_id']))).all())
        await ingest(jobs[0].id)
        async with AsyncSessionLocal() as db:
            job = await db.get(IngestionJob, jobs[1].id)
            job.attempts, job.content_hash = 2, 'invalid'
            await db.commit()
        with pytest.raises(ValueError):
            await ingest(jobs[1].id)
        async with AsyncSessionLocal() as db:
            assert (await db.get(KnowledgeBase,kb)).index_batch_id == ''
            assert {d.id:d.active_version for d in (await db.scalars(select(Document))).all()} == old
            assert set((await db.scalars(select(IngestionJob.status).where(IngestionJob.batch_id==response.json()['batch_id']))).all()) == {'failed'}
            assert await db.scalar(select(func.count()).select_from(DocumentChunk)) == len(docs)
        assert await KnowledgeRetriever(uid, [kb]).ainvoke('华东折扣')


@pytest.mark.asyncio
async def test_repair_restores_missing_vectors_prunes_orphans_and_protects_inflight(providers):
    uid, other, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        doc_id = await upload(client,uid,kb)
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(DocumentChunk).where(DocumentChunk.doc_id==doc_id))
            profile, version = row.embedding_profile, row.version
            pending = IngestionJob(user_id=uid, doc_id=doc_id, content_hash='unused')
            db.add(pending); await db.commit()
            pending_version = pending.version
        index.delete_document(doc_id)
        stale = str(uuid.uuid4())
        index.upsert([dict(id='orphan',user_id=uid,kb_id=kb,doc_id=doc_id,version=stale),
            dict(id='inflight',user_id=uid,kb_id=kb,doc_id=doc_id,version=pending_version),
            dict(id='other-user',user_id=other,kb_id=kb,doc_id='foreign',version=stale)], [[1.,0.,0.]]*3, profile)
        result = await repair_index(uid,kb)
        assert result == {'checked_chunks':1,'restored_vectors':1,'removed_vectors':1}
        assert index.ids(profile,3,uid,kb,[pending_version]) == {'inflight'}
        assert index.ids(profile,3,other,kb,[stale]) == {'other-user'}
        assert await KnowledgeRetriever(uid,[kb]).ainvoke('华东折扣')
        assert (await client.post(f'/api/knowledge/bases/{kb}/repair',headers=auth(other))).status_code == 404


@pytest.mark.asyncio
async def test_delete_durably_cleans_original_and_artifacts_with_retry(providers, monkeypatch):
    uid, _, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        doc_id = await upload(client,uid,kb)
        async with AsyncSessionLocal() as db:
            original = (await db.get(Document,doc_id)).file_path
            version = (await db.get(Document,doc_id)).active_version
        assert (await client.delete(f'/api/knowledge/documents/{doc_id}',headers=auth(uid))).status_code==204
        async with AsyncSessionLocal() as db:
            job_id = await db.scalar(select(MaintenanceJob.id))
        delete = store.delete
        def broken(*args): raise OSError('transient storage error')
        monkeypatch.setattr(store,'delete',broken)
        with pytest.raises(OSError): await maintain(job_id)
        async with AsyncSessionLocal() as db:
            assert (await db.get(MaintenanceJob,job_id)).status == 'retrying'
        monkeypatch.setattr(store,'delete',delete)
        await maintain(job_id)
        await maintain(job_id)  # ready tasks are idempotent
        with pytest.raises(FileNotFoundError): store.read(original)
        assert not (settings.USER_STORAGE_DIR / uid / 'artifacts' / doc_id).exists()


@pytest.mark.asyncio
async def test_keyword_fallback_threshold_preview_and_scoped_debug(providers, monkeypatch):
    uid, other, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        doc_id = await upload(client,uid,kb)
        assert (await client.get(f'/api/knowledge/documents/{doc_id}/chunks',headers=auth(other))).status_code==404
        preview = await client.get(f'/api/knowledge/documents/{doc_id}/chunks',headers=auth(uid))
        assert preview.json()['total']==1 and '华东' in preview.json()['items'][0]['content']
        async def broken(self,texts): raise httpx.ConnectError('do-not-expose-secret')
        monkeypatch.setattr(EmbeddingProvider,'embed',broken)
        response = await client.post(f'/api/knowledge/bases/{kb}/search',headers=auth(uid),json={'query':'华东折扣'})
        assert response.status_code==200 and response.json()['items']
        assert response.json()['diagnostics']['effective_mode']=='keyword'
        assert response.json()['diagnostics']['warnings'] and 'do-not-expose-secret' not in response.text
        assert (await client.post(f'/api/knowledge/bases/{kb}/search',headers=auth(uid),json={'query':'折扣','mode':'vector'})).status_code==422
        async def unrelated(self,texts): return [[0.,1.,0.] for _ in texts]
        monkeypatch.setattr(EmbeddingProvider,'embed',unrelated)
        response = await client.post(f'/api/knowledge/bases/{kb}/search',headers=auth(uid),json={'query':'火星宇宙飞船','min_similarity':0.8})
        assert response.json()['items']==[]
        assert not response.json()['diagnostics']['warnings']


@pytest.mark.asyncio
async def test_embedding_http_contract_reorders_and_rejects_invalid_vectors(monkeypatch):
    from openai import AsyncOpenAI
    response = {'data':[{'index':1,'embedding':[0.,1.]},{'index':0,'embedding':[1.,0.]}]}
    def handler(request):
        assert request.headers['Authorization']=='Bearer private-key'
        assert json.loads(request.content)['input']==['a','b']
        return httpx.Response(200,json=response)
    monkeypatch.setattr('app.infrastructure.embeddings.AsyncOpenAI',lambda **kwargs: AsyncOpenAI(**kwargs,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    provider=EmbeddingProvider({'base_url':'http://test/v1','model_id':'test','api_key':'private-key'})
    assert await provider.embed(['a','b']) == [[1.,0.],[0.,1.]]
    response['data'][0]['index']=0
    with pytest.raises(ValueError,match='数量或顺序'): await provider.embed(['a','b'])
    response['data']=[{'index':0,'embedding':[0.,0.]},{'index':1,'embedding':[1.,0.]}]
    with pytest.raises(ValueError,match='无效向量'): await provider.embed(['a','b'])


@pytest.mark.asyncio
async def test_model_profile_resolves_previous_config_after_default_switch(monkeypatch):
    from app.models.config import AppConfig
    from app.infrastructure.credentials import encrypt
    uid, _, _ = await seed()
    async with AsyncSessionLocal() as db:
        old = {'base_url':'http://old-provider/v1','model_id':'old-embedding','api_key':'old-key'}
        db.add(AppConfig(user_id=uid,config_key='model_setting',config_value=json.dumps({
            'default_embedding_model':'new-embedding','available_models':[
                {'id':'old-embedding','base_url':old['base_url'],'api_key':encrypt(old['api_key']),'type':'embedding'},
                {'id':'new-embedding','base_url':'http://new-provider/v1','api_key':encrypt('new-key'),'type':'embedding'}]})))
        await db.commit()
        assert (await EmbeddingProvider.for_user(db,uid)).config['model_id']=='new-embedding'
        resolved = await EmbeddingProvider.for_profile(db,uid,EmbeddingProvider(old).profile)
        assert resolved.config['model_id']=='old-embedding' and resolved.config['api_key']=='old-key'


@pytest.mark.asyncio
async def test_cancelled_vector_write_settles_before_cleanup_can_run(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        release.wait(timeout=5)
        finished.set()
    monkeypatch.setattr(index,'upsert',slow)
    task=asyncio.create_task(write_vectors([],[],'profile'))
    await asyncio.to_thread(started.wait,5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert finished.is_set()


def test_relevance_metrics_are_document_level_and_handle_unanswerable_queries():
    import runpy
    from pathlib import Path
    metrics=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts'/'validate_knowledge.py'))['metrics']
    report=metrics([{'query':'q','expected_doc_ids':['policy','manual']},{'query':'unknown','no_answer':True}],
        [[{'doc_id':'irrelevant'},{'doc_id':'policy'},{'doc_id':'policy'}],[]])
    assert report['recall_at_k']==0.5 and report['mrr']==0.5 and report['no_answer_accuracy']==1


@pytest.mark.asyncio
async def test_base_management_deletion_queues_cleanup_without_leaking_credentials(providers):
    uid, other, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        doc_id=await upload(client,uid,kb)
        assert (await client.patch(f'/api/knowledge/bases/{kb}',headers=auth(other),json={'name':'no'})).status_code==404
        edited=await client.patch(f'/api/knowledge/bases/{kb}',headers=auth(uid),json={'name':'更新政策','description':'新说明'})
        assert edited.json()['name']=='更新政策' and edited.json()['document_count']==1
        jobs=await client.get(f'/api/knowledge/bases/{kb}/jobs',headers=auth(uid))
        assert 'embedding_config' not in jobs.text and 'test-secret' not in jobs.text
        assert (await client.delete(f'/api/knowledge/bases/{kb}',headers=auth(uid))).status_code==200
        async with AsyncSessionLocal() as db:
            assert await db.get(Document,doc_id) is None
            assert await db.scalar(select(func.count()).select_from(IngestionJob))==0
            task=await db.scalar(select(MaintenanceJob.id))
        await maintain(task)
        assert (await client.get(f'/api/knowledge/documents/{doc_id}/download',headers=auth(uid))).status_code==404


@pytest.mark.asyncio
async def test_delete_during_parse_schedules_cleanup_for_late_artifacts(providers,monkeypatch):
    import app.ingestion.pipeline as pipeline
    from app.ingestion.parser import parse_document
    uid, _, kb=await seed()
    started,release=threading.Event(),threading.Event()
    def paused(path,version):
        result=parse_document(path,version)
        started.set(); release.wait(timeout=5)
        return result
    monkeypatch.setattr(pipeline,'parse_document',paused)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post(f'/api/knowledge/bases/{kb}/documents/upload',headers=auth(uid),
            files={'file':('policy.txt','审批政策'.encode(),'text/plain')})
        doc_id=response.json()['id']
        async with AsyncSessionLocal() as db:
            job_id=await db.scalar(select(IngestionJob.id).where(IngestionJob.doc_id==doc_id))
        task=asyncio.create_task(ingest(job_id))
        try:
            assert await asyncio.to_thread(started.wait,5)
            assert (await client.delete(f'/api/knowledge/documents/{doc_id}',headers=auth(uid))).status_code==204
            async with AsyncSessionLocal() as db:
                cleanup=await db.scalar(select(MaintenanceJob.id))
            await maintain(cleanup)
        finally:
            release.set()
        await task
        async with AsyncSessionLocal() as db:
            late_jobs=list((await db.scalars(select(MaintenanceJob.id).where(MaintenanceJob.status=='queued'))).all())
        assert late_jobs
        for job_id in late_jobs: await maintain(job_id)
        root=settings.USER_STORAGE_DIR/uid/'artifacts'/doc_id
        assert not list(root.rglob('*.json')) and not list(root.rglob('*.md'))
