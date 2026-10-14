import asyncio
from datetime import datetime, timedelta
from celery import Celery
from sqlalchemy import select, or_, and_, update
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.platform import IngestionJob, AgentRun

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

@celery.task(name='rag.ingest', autoretry_for=(Exception,), retry_backoff=10, retry_jitter=True, max_retries=2)
def ingest_document(job_id):
    from app.ingestion.pipeline import ingest
    asyncio.run(run_and_dispose(ingest(job_id)))

async def pending_jobs():
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(select(IngestionJob.id).where(or_(
            IngestionJob.status.in_(['queued', 'retrying']),
            and_(IngestionJob.status == 'processing', IngestionJob.updated_at < datetime.utcnow() - timedelta(minutes=15))
        )).limit(100))).all())

async def pending_agent_runs():
    from app.workers.local import recover_expired_agent_runs
    await recover_expired_agent_runs()
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(select(AgentRun.id).where(AgentRun.status == 'queued')
            .order_by(AgentRun.created_at).limit(100))).all())

@celery.task(name='rag.dispatch_pending')
def dispatch_pending():
    for job_id in asyncio.run(run_and_dispose(pending_jobs())):
        ingest_document.delay(job_id)
    for run_id in asyncio.run(run_and_dispose(pending_agent_runs())):
        run_agent.delay(run_id)
    from app.workers.local import pending_maintenance
    for job_id in asyncio.run(run_and_dispose(pending_maintenance())):
        maintain_document.delay(job_id)


@celery.task(name='rag.maintain')
def maintain_document(job_id):
    from app.ingestion.maintenance import maintain
    asyncio.run(run_and_dispose(maintain(job_id)))

@celery.task(name='rag.agent_run')
def run_agent(run_id):
    from app.application.chat import execute_agent_run
    asyncio.run(run_and_dispose(execute_agent_run(run_id)))
