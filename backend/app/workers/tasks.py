import asyncio
from celery import Celery
from app.config import settings
from app.database import engine
from app.application.chat import recover_expired_agent_runs, pending_agent_runs

celery = Celery('rag', broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
                   broker_connection_retry_on_startup=True, broker_connection_timeout=2, task_publish_retry=False, task_soft_time_limit=780, task_time_limit=840,
                   worker_concurrency=settings.AGENT_WORKER_CONCURRENCY,
                   beat_schedule={'recover-background-jobs': {'task': 'rag.dispatch_pending', 'schedule': 15.0}})

async def run_and_dispose(coro):
    try:
        return await coro
    finally:
        await engine.dispose()

@celery.task(name='rag.dispatch_pending')
def dispatch_pending():
    async def pending():
        await recover_expired_agent_runs()
        return await pending_agent_runs(100)
    for run_id in asyncio.run(run_and_dispose(pending())):
        run_agent.delay(run_id)

@celery.task(name='rag.agent_run')
def run_agent(run_id):
    from app.application.chat import execute_agent_run
    asyncio.run(run_and_dispose(execute_agent_run(run_id)))
