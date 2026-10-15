"""Resolve stable result references from the authorized durable evidence archive."""
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.platform import AgentRun, RunEvent

async def tool_result(user_id: str, conversation_id: str, scope_version: int, reference: str):
    async with AsyncSessionLocal() as db:
        payload = await db.scalar(select(RunEvent.payload).join(AgentRun, AgentRun.id == RunEvent.run_id).where(
            AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id,
            AgentRun.scope_version == scope_version, RunEvent.event_type == 'CUSTOM',
            RunEvent.payload['name'].as_string() == 'business.evidence',
            RunEvent.payload['value']['type'].as_string() == 'tool_result',
            RunEvent.payload['value']['tool_result_id'].as_string() == reference).limit(1))
        if not payload:
            raise ValueError('工具结果不存在或不属于当前业务范围')
        return payload['value']['result']

async def query_result(user_id: str, conversation_id: str, scope_version: int, reference: str):
    async with AsyncSessionLocal() as db:
        from sqlalchemy import or_
        stmt = select(RunEvent.payload).join(AgentRun, AgentRun.id == RunEvent.run_id).where(
            AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id,
            AgentRun.scope_version == scope_version, RunEvent.event_type == 'CUSTOM',
            RunEvent.payload['name'].as_string() == 'business.evidence',
            RunEvent.payload['value']['type'].as_string() == 'query_result',
            or_(
                RunEvent.payload['value']['citation_id'].as_string() == reference,
                RunEvent.payload['value']['query_id'].as_string() == reference
            ))
        payload = await db.scalar(stmt.limit(1))
        if not payload:
            raise ValueError('查询结果不存在或不属于当前业务范围')
        return payload['value']


async def run_queries(user_id: str, conversation_id: str, scope_version: int, run_id: str):
    """Recover a run's evidence once; message presentation is never execution state."""
    async with AsyncSessionLocal() as db:
        payloads = (await db.scalars(select(RunEvent.payload).join(AgentRun, AgentRun.id == RunEvent.run_id).where(
            AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id,
            AgentRun.scope_version == scope_version, AgentRun.id == run_id,
            RunEvent.event_type == 'CUSTOM', RunEvent.payload['name'].as_string() == 'business.evidence',
            RunEvent.payload['value']['type'].as_string() == 'query_result').order_by(RunEvent.sequence))).all()
        return list({payload['value']['query_id']: payload['value'] for payload in payloads}.values())
