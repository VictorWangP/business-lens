"""Resolve stable result references from the authorized durable evidence archive."""
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.platform import AgentRun, RunEvent

async def query_result(user_id: str, conversation_id: str, scope_version: int, reference: str):
    async with AsyncSessionLocal() as db:
        stmt = select(RunEvent.payload).join(AgentRun, AgentRun.id == RunEvent.run_id).where(
            AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id,
            AgentRun.scope_version == scope_version, RunEvent.event_type == 'CUSTOM',
            RunEvent.payload['name'].as_string() == 'business.evidence',
            RunEvent.payload['value']['citation_id'].as_string() == reference,
            RunEvent.payload['value']['type'].as_string() == 'query_result')
        payload = await db.scalar(stmt.limit(1))
        if not payload:
            raise ValueError('查询结果不存在或不属于当前业务范围')
        return payload['value']

async def source_citations(user_id, conversation_id, scope_version, references, kb_ids):
    from app.retrieval.retriever import read_chunk
    found = {}
    async with AsyncSessionLocal() as db:
        stmt = select(RunEvent.payload).join(AgentRun, AgentRun.id == RunEvent.run_id).where(
            AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id,
            AgentRun.scope_version == scope_version, RunEvent.event_type == 'CUSTOM',
            RunEvent.payload['name'].as_string() == 'business.evidence',
            RunEvent.payload['value']['type'].as_string() == 'citations').order_by(RunEvent.created_at.desc())
        async for payload in await db.stream_scalars(stmt):
            for citation in payload['value']['items']:
                if citation['id'] in references and citation['id'] not in found:
                    # Recheck current document access and active version before reusing evidence.
                    await read_chunk(user_id, kb_ids, citation['chunk_id'])
                    found[citation['id']] = citation
            if references <= found.keys():
                return found
    raise ValueError('来源引用已失效或不属于当前业务范围，请重新检索')
