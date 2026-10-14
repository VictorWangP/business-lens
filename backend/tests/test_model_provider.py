from agent_helpers import chat_input
"""Provider discovery, credential reuse, and editing with real HTTP/SDK contracts."""
import json
import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.config import AppConfig
from app.infrastructure.credentials import decrypt
from app.services.model_provider import list_provider_models
from main import app
from test_platform import seed, auth

def mock_provider(monkeypatch, handler):

    def factory(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr('app.services.model_provider.AsyncOpenAI', factory)

@pytest.mark.asyncio
async def test_model_discovery_authenticates_and_deduplicates(monkeypatch):

    def handler(request):
        assert str(request.url) == 'https://provider.test/v1/models'
        assert request.headers['Authorization'] == 'Bearer provider-secret'
        return httpx.Response(200, json={'object': 'list', 'data': [{'id': 'model-b'}, {'id': 'model-a'}, {'id': 'model-a'}]})
    mock_provider(monkeypatch, handler)
    assert await list_provider_models('https://provider.test/v1/', 'provider-secret') == ['model-a', 'model-b']

@pytest.mark.parametrize('status, expected', [(401, '认证失败'), (403, '认证失败'), (404, '手动填写'), (429, '限流'), (500, 'HTTP 500')])
@pytest.mark.asyncio
async def test_provider_failure_does_not_expose_response_secrets(monkeypatch, status, expected):
    mock_provider(monkeypatch, lambda request: httpx.Response(status, json={'error': {'message': 'secret-do-not-return'}}))
    with pytest.raises(ValueError, match=expected) as err:
        await list_provider_models('https://provider.test/v1', 'key')
    assert 'secret-do-not-return' not in str(err.value)

@pytest.mark.asyncio
async def test_local_provider_and_invalid_addresses(monkeypatch):

    def handler(request):
        assert request.headers['Authorization'] == 'Bearer local'
        return httpx.Response(200, json={'data': []})
    mock_provider(monkeypatch, handler)
    assert await list_provider_models('http://localhost:11434/v1', 'local') == []
    for base in ['file:///etc/passwd', 'https://name:password@provider.test/v1', 'https://provider.test/v1?key=secret']:
        with pytest.raises(ValueError, match='Base URL'):
            await list_provider_models(base, 'key')
    with pytest.raises(ValueError, match='API Key'):
        await list_provider_models('https://provider.test/v1', '')

@pytest.mark.parametrize('failure, expected', [(httpx.ConnectError, '无法连接'), (httpx.ReadTimeout, '超时')])
@pytest.mark.asyncio
async def test_network_failures(monkeypatch, failure, expected):

    def handler(request):
        raise failure('internal secret', request=request)
    mock_provider(monkeypatch, handler)
    with pytest.raises(ValueError, match=expected):
        await list_provider_models('https://provider.test/v1', 'key')

@pytest.mark.asyncio
async def test_edit_rename_bulk_reuse_and_cross_user_isolation(monkeypatch):
    a, b, _ = await seed()

    def handler(request):
        assert request.headers['Authorization'] == 'Bearer provider-secret'
        return httpx.Response(200, json={'data': [{'id': 'model-a'}, {'id': 'model-b'}]})
    mock_provider(monkeypatch, handler)
    base = 'https://provider.test/v1'
    config = {'default_model': 'old-id', 'available_models': [{'id': 'old-id', 'name': 'Original', 'base_url': base, 'api_key': 'provider-secret'}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.put('/api/settings/app-config/model_setting', headers=auth(a), json={'config_value': config})).status_code == 200
        probe = {'base_url': base, 'api_key': '********', 'credential_model_id': 'old-id'}
        for endpoint in ['models', 'test']:
            response = await client.post(f'/api/settings/model-provider/{endpoint}', headers=auth(a), json=probe)
            assert response.status_code == 200, response.text
            assert response.json()['models'] == ['model-a', 'model-b']
            assert 'provider-secret' not in response.text
        assert (await client.post('/api/settings/model-provider/models', headers=auth(b), json=probe)).status_code == 422
        assert (await client.post('/api/settings/model-provider/models', headers=auth(a), json={**probe, 'base_url': 'https://other.test/v1'})).status_code == 422
        config['default_model'] = 'model-a'
        config['available_models'] = [{'id': mid, 'name': mid, 'base_url': base, 'api_key': '********', 'credential_model_id': 'old-id'} for mid in ['model-a', 'model-b']]
        response = await client.put('/api/settings/app-config/model_setting', headers=auth(a), json={'config_value': config})
        assert response.status_code == 200, response.text
        saved = (await client.get('/api/settings/app-config', headers=auth(a))).json()['model_setting']
        assert saved['default_model'] == 'model-a'
        assert [m['api_key'] for m in saved['available_models']] == ['********', '********']
        config['available_models'].append(config['available_models'][0])
        assert (await client.put('/api/settings/app-config/model_setting', headers=auth(a), json={'config_value': config})).status_code == 422
    async with AsyncSessionLocal() as db:
        cfg = await db.scalar(select(AppConfig).where(AppConfig.user_id == a, AppConfig.config_key == 'model_setting'))
        models = json.loads(cfg.config_value)['available_models']
        assert all((decrypt(m['api_key']) == 'provider-secret' for m in models))
        assert all(('credential_model_id' not in m for m in models))

@pytest.mark.asyncio
async def test_new_user_requires_ui_models_and_ignores_environment(monkeypatch):
    from app.services.llm_service import LLMService, ModelUnavailable
    from app.infrastructure.embeddings import EmbeddingProvider
    for key, value in {'OPENAI_API_BASE': 'https://environment.test/v1', 'OPENAI_API_KEY': 'environment-secret', 'DEFAULT_MODEL': 'env-llm', 'EMBEDDING_API_BASE': 'https://environment.test/v1', 'EMBEDDING_API_KEY': 'environment-secret', 'EMBEDDING_MODEL': 'env-embed'}.items():
        monkeypatch.setenv(key, value)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/auth/register', json={'username': 'unconfigured', 'password': 'StrongPassword123', 'email': 'unconfigured@example.com'})
        assert response.status_code == 200, response.text
        uid = response.json()['user']['id']
        model = (await client.get('/api/settings/app-config', headers=auth(uid))).json()['model_setting']
        assert model['available_models'] == []
        assert not model['default_model'] and (not model['default_embedding_model'])
        kb = (await client.post('/api/knowledge/bases', headers=auth(uid), json={'name': '模型校验'})).json()
        workspace = (await client.post('/api/workspaces', headers=auth(uid), json={'name': '模型校验', 'kb_ids': [kb['id']]})).json()
        chat = await client.post('/api/chat/stream', headers=auth(uid), json=chat_input(**{'query': '你好', 'workspace_id': workspace['id']}))
        assert chat.status_code == 422 and '模型设置' in chat.json()['detail']
        async with AsyncSessionLocal() as db:
            with pytest.raises(ModelUnavailable, match='配置并选择嵌入模型'):
                await EmbeddingProvider.for_user(db, uid)
            with pytest.raises(ModelUnavailable, match='未配置'):
                await LLMService.get_model_config(db, uid, model_id='env-llm')
        config = {'default_model': 'user-llm', 'default_embedding_model': 'user-embed', 'available_models': [{'id': 'user-llm', 'name': 'My LLM', 'type': 'llm', 'base_url': 'https://user.test/v1', 'api_key': 'user-llm-key'}, {'id': 'user-embed', 'name': 'My Embedding', 'type': 'embedding', 'base_url': 'https://embed.test/v1', 'api_key': 'user-embed-key'}]}
        assert (await client.put('/api/settings/app-config/model_setting', headers=auth(uid), json={'config_value': config})).status_code == 200
        async with AsyncSessionLocal() as db:
            llm = await LLMService.get_model_config(db, uid)
            assert (llm['model_id'], llm['base_url'], llm['api_key']) == ('user-llm', 'https://user.test/v1', 'user-llm-key')
            embed = await EmbeddingProvider.for_user(db, uid)
            assert (embed.config['model_id'], embed.config['api_key']) == ('user-embed', 'user-embed-key')
            with pytest.raises(ModelUnavailable, match='不是 embedding'):
                await LLMService.get_model_config(db, uid, 'user-llm', kind='embedding')
        for missing, message in [('api_key', 'API Key'), ('base_url', 'Base URL')]:
            async with AsyncSessionLocal() as db:
                cfg = await db.scalar(select(AppConfig).where(AppConfig.user_id == uid, AppConfig.config_key == 'model_setting'))
                value = json.loads(cfg.config_value)
                original = value['available_models'][0].pop(missing)
                cfg.config_value = json.dumps(value)
                await db.commit()
                with pytest.raises(ModelUnavailable, match=message):
                    await LLMService.get_model_config(db, uid)
                value['available_models'][0][missing] = original
                cfg.config_value = json.dumps(value)
                await db.commit()
