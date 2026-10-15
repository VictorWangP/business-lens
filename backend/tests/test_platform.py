from agent_helpers import chat_input
import asyncio
import hashlib
import json
from pathlib import Path
import httpx
import pytest
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.platform import AgentRun, RunEvent, DataSource
from app.security.auth import create_access_token
from app.infrastructure.credentials import encrypt, decrypt
from app.infrastructure.embeddings import EmbeddingProvider
from app.config import settings
from main import app

async def seed():
    async with AsyncSessionLocal() as db:
        a, b = (User(username='alice', hashed_password='unused'), User(username='bob', hashed_password='unused'))
        db.add_all([a, b])
        await db.commit()
        return (a.id, b.id)

def auth(uid):
    return {'Authorization': 'Bearer ' + create_access_token({'sub': uid})}

@pytest.mark.asyncio
async def test_registration_has_no_synthetic_sources():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/auth/register', json={'username': 'real-user', 'password': 'StrongPassword123', 'email': 'real@example.com'})
        assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DataSource)) == 0

@pytest.mark.asyncio
async def test_source_secret_never_returned_and_cross_user_denied():
    a, b = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/data-sources', headers=auth(a), json={'name': 'ERP', 'connection_url': 'postgresql://reader:password@localhost/business', 'schema_name': 'reporting', 'allowed_views': ['sales']})
        assert result.status_code == 200, result.text
        assert 'password' not in result.text and 'connection_secret' not in result.text
        source_id = result.json()['id']
        assert (await client.get('/api/data-sources', headers=auth(b))).json() == []
        assert (await client.post(f'/api/data-sources/{source_id}/test', headers=auth(b))).status_code == 404
        denied = await client.post('/api/workspaces', headers=auth(b), json={'name': '越权来源', 'source_ids': [source_id]})
        assert denied.status_code == 403
        space = (await client.post('/api/workspaces', headers=auth(a), json={'name': 'ERP空间', 'source_ids': [source_id]})).json()
        assert (await client.post('/api/chat/stream', headers=auth(b), json=chat_input(**{'query': 'sales', 'workspace_id': space['id']}))).status_code == 404

@pytest.mark.asyncio
async def test_missing_model_fails_before_creating_success_message():
    a, _ = await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/data-sources', headers=auth(a), json={'name': 'ERP', 'connection_url': 'postgresql://reader:password@localhost/business', 'schema_name': 'reporting', 'allowed_views': ['sales']})
        source_id = result.json()['id']
        space = (await client.post('/api/workspaces', headers=auth(a), json={'name': '业务空间', 'source_ids': [source_id]})).json()
        response = await client.post('/api/chat/stream', headers=auth(a), json=chat_input(**{'query': '总结业务', 'workspace_id': space['id']}))
        assert response.status_code == 422
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0

def test_credentials_authenticated_encryption():
    value = encrypt('private-password')
    assert 'private-password' not in value
    assert decrypt(value) == 'private-password'
    with pytest.raises(ValueError):
        decrypt('legacy-plaintext')
