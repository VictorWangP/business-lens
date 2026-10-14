"""Shared standard-protocol helpers for opt-in acceptance commands."""
import asyncio
import uuid
from contextlib import asynccontextmanager
from ag_ui.core import RunAgentInput, UserMessage

def chat_input(query, workspace_id=None, conversation_id=None, model=None):
    return RunAgentInput(thread_id=conversation_id or str(uuid.uuid4()), run_id=str(uuid.uuid4()),
        messages=[UserMessage(id=str(uuid.uuid4()), content=query)], state={}, tools=[], context=[],
        forwarded_props={'workspace_id':workspace_id,'model':model}).model_dump(mode='json',by_alias=True,exclude_none=True)

@asynccontextmanager
async def agent_worker():
    from app.workers.local import run_agent_worker
    task=asyncio.create_task(run_agent_worker())
    try:yield
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
