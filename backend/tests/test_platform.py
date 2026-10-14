import asyncio
import hashlib
import json
from pathlib import Path
import httpx
import pytest
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.knowledge import KnowledgeBase, Document
from app.models.platform import IngestionJob, DocumentChunk, AgentRun, RunEvent
from app.models.business import SalesOrder
from app.security.auth import create_access_token
from app.infrastructure.credentials import encrypt, decrypt
from app.infrastructure.embeddings import EmbeddingProvider
from app.ingestion.pipeline import ingest
from app.retrieval.retriever import KnowledgeRetriever
from app.config import settings
from main import app

async def seed():
    async with AsyncSessionLocal() as db:
        a, b = User(username='alice', hashed_password='unused'), User(username='bob', hashed_password='unused')
        db.add_all([a, b]); await db.flush()
        kb = KnowledgeBase(user_id=a.id, name='政策', description='真实上传')
        db.add(kb); await db.commit()
        return a.id, b.id, kb.id

def auth(uid):
    return {'Authorization': 'Bearer ' + create_access_token({'sub': uid})}

@pytest.mark.asyncio
async def test_registration_has_no_synthetic_orders():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/auth/register', json={'username':'real-user','password':'StrongPassword123','email':'real@example.com'})
        assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SalesOrder)) == 0

@pytest.mark.asyncio
async def test_source_secret_never_returned_and_cross_user_denied():
    a, b, _ = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/data-sources', headers=auth(a), json={
            'name':'ERP','connection_url':'postgresql://reader:password@localhost/business',
            'schema_name':'reporting','allowed_views':['sales']})
        assert result.status_code == 200, result.text
        assert 'password' not in result.text and 'connection_secret' not in result.text
        source_id = result.json()['id']
        assert (await client.get('/api/data-sources', headers=auth(b))).json() == []
        assert (await client.post(f'/api/data-sources/{source_id}/test', headers=auth(b))).status_code == 404
        denied = await client.post('/api/workspaces', headers=auth(b), json={'name':'越权来源','source_ids':[source_id]})
        assert denied.status_code == 403
        space = (await client.post('/api/workspaces', headers=auth(a), json={'name':'ERP空间','source_ids':[source_id]})).json()
        assert (await client.post('/api/chat/stream', headers=auth(b), json={'query':'sales','workspace_id':space['id']})).status_code == 404

@pytest.mark.asyncio
async def test_missing_model_fails_before_creating_success_message():
    a, _, kb = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        space = (await client.post('/api/workspaces', headers=auth(a), json={'name':'政策空间','kb_ids':[kb]})).json()
        response = await client.post('/api/chat/stream', headers=auth(a), json={'query':'总结政策','workspace_id':space['id']})
        assert response.status_code == 422
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0

@pytest.mark.asyncio
async def test_ingestion_activation_retry_retrieval_and_isolation(monkeypatch):
    a, b, kb = await seed()
    content = ('华东客户折扣政策：审批后享有百分之五折扣。\n' * 100).encode()
    path = settings.USER_STORAGE_DIR / a / 'policy.txt'
    path.parent.mkdir(parents=True); path.write_bytes(content)
    async with AsyncSessionLocal() as db:
        doc = Document(user_id=a, kb_id=kb, filename='policy.txt', file_path=str(path), file_size=len(content))
        db.add(doc); await db.flush()
        job = IngestionJob(user_id=a, doc_id=doc.id, content_hash=hashlib.sha256(content).hexdigest())
        db.add(job); await db.commit()
        job_id, doc_id = job.id, doc.id
    # Deterministic transport substitute; production never uses this provider.
    async def for_user(cls, db, user):
        return cls({'base_url':'http://test/v1','model_id':'test-embedding','api_key':'test'})
    async def embed(self, texts):
        return [[1., 0., 0.] for text in texts]
    monkeypatch.setattr(EmbeddingProvider, 'for_user', classmethod(for_user))
    monkeypatch.setattr(EmbeddingProvider, 'embed', embed)
    await ingest(job_id)
    await ingest(job_id)
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        assert doc.status == 'ready' and doc.chunk_count > 1
        old_version = doc.active_version
        count = await db.scalar(select(func.count()).select_from(DocumentChunk))
        assert count == doc.chunk_count
        assert (await db.get(IngestionJob, job_id)).attempts == 1
    results = await KnowledgeRetriever(a, [kb]).aretrieve('华东折扣')
    assert results and len(results[0].node.text) > 300
    assert await KnowledgeRetriever(b, [kb]).aretrieve('华东折扣') == []
    async with AsyncSessionLocal() as db:
        failed = IngestionJob(user_id=a, doc_id=doc_id, content_hash='changed')
        db.add(failed); await db.commit(); failed_id = failed.id
    with pytest.raises(ValueError):
        await ingest(failed_id)
    async with AsyncSessionLocal() as db:
        assert (await db.get(Document, doc_id)).active_version == old_version
    assert await KnowledgeRetriever(a, [kb]).aretrieve('华东折扣')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        chunk_id = results[0].node.node_id
        assert (await client.get(f'/api/knowledge/chunks/{chunk_id}', headers=auth(b))).status_code == 404
        assert (await client.delete(f'/api/knowledge/documents/{doc_id}', headers=auth(a))).status_code == 204
    assert await KnowledgeRetriever(a, [kb]).aretrieve('华东折扣') == []


def test_credentials_authenticated_encryption():
    value = encrypt('private-password')
    assert 'private-password' not in value
    assert decrypt(value) == 'private-password'
    with pytest.raises(ValueError):
        decrypt('legacy-plaintext')
