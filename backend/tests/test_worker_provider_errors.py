"""Permanent provider failures stop retrying without exposing raw response data."""
import warnings

import httpx
import pytest
from openai import AsyncOpenAI

from app.database import AsyncSessionLocal
from app.infrastructure.embeddings import EmbeddingProvider
from app.models.frequent import QuestionRecord
from app.workers import frequent, local
from test_frequent import providers, seed, message

ORIGINAL_EMBED = EmbeddingProvider.embed


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_embedding_auth_failures_are_terminal(providers, monkeypatch, caplog, status):
    user, _, conversation, _, _ = await seed()
    mid = await message(user, conversation)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == '/v1/embeddings'
        return httpx.Response(status, json={'error': {
            'message': 'private-provider-detail', 'type': 'provider_error'}})

    # Keep the real embeddings SDK boundary; only replace HTTP transport.
    monkeypatch.setattr(EmbeddingProvider, 'embed', ORIGINAL_EMBED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr('app.infrastructure.embeddings.AsyncOpenAI',
                            lambda **kwargs: AsyncOpenAI(**kwargs, http_client=client))
        await frequent.process(mid)
        async with AsyncSessionLocal() as db:
            record = await db.get(QuestionRecord, mid)
            assert record.attempts == 1
            assert record.status == ('failed' if status in {401, 403} else 'pending')
            assert 'private-provider-detail' not in record.error_code
        if status in {401, 403}:
            await frequent.recover()
            assert mid not in await frequent.pending_ids()
            await frequent.process(mid)
            assert len(calls) == 1
    assert 'private-provider-detail' not in caplog.text


@pytest.mark.asyncio
async def test_idle_worker_polling_has_no_deprecated_utc_calls():
    with warnings.catch_warnings():
        assert await local.pending_agent_runs(10) == []
        await local.recover_expired_agent_runs()
