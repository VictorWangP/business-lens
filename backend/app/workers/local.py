"""Run with python -m app.workers.local. One lightweight process; no Redis or Docker needed."""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update, or_, and_
from app.database import AsyncSessionLocal, engine
from app.models.platform import IngestionJob, AgentRun, MaintenanceJob
from app.ingestion.pipeline import ingest
from app.ingestion.maintenance import maintain
from app.config import settings

logger=logging.getLogger(__name__)

async def pending_jobs():
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        return list((await db.scalars(select(IngestionJob.id).where(or_(
            IngestionJob.status=='queued',
            and_(IngestionJob.status=='retrying',IngestionJob.updated_at < now-timedelta(seconds=15)),
            and_(IngestionJob.status=='processing',IngestionJob.updated_at < now-timedelta(minutes=15))
        )).order_by(IngestionJob.created_at).limit(20))).all())


async def recover_expired_agent_runs():
    from app.application.chat import persist_run_event
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        runs = (await db.execute(select(AgentRun.id, AgentRun.status).where(
            AgentRun.status.in_(['running', 'cancel_requested']),
            or_(AgentRun.lease_expires_at.is_(None), AgentRun.lease_expires_at < now)
        ))).all()
        recovered = []
        for run in runs:
            cancelled = run.status == 'cancel_requested'
            result = await db.execute(update(AgentRun).where(
                AgentRun.id == run.id, AgentRun.status == run.status,
                or_(AgentRun.lease_expires_at.is_(None), AgentRun.lease_expires_at < now)
            ).values(status='cancelled' if cancelled else 'failed',
                     error='用户停止' if cancelled else '执行进程中断，请重新发起任务',
                     finished_at=now, lease_expires_at=None))
            if result.rowcount == 1:
                recovered.append((run.id, cancelled))
        await db.commit()
    for run_id, cancelled in recovered:
        if not cancelled:
            await persist_run_event(run_id, {'type': 'error', 'message': '执行进程中断，请重新发起任务'})
        await persist_run_event(run_id, {'type': 'done', 'status': 'cancelled' if cancelled else 'failed'})


async def pending_agent_runs(limit: int):
    if settings.TASK_BACKEND != 'database' or limit <= 0:
        return []
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(select(AgentRun.id).where(AgentRun.status == 'queued')
            .order_by(AgentRun.created_at).limit(limit))).all())

async def run_agent_worker():
    agent_tasks: set[asyncio.Task] = set()
    try:
        while True:
            await recover_expired_agent_runs()
            free_slots = max(0, settings.AGENT_WORKER_CONCURRENCY - len(agent_tasks))
            for run_id in await pending_agent_runs(free_slots):
                task = asyncio.create_task(run_agent_safely(run_id))
                agent_tasks.add(task)
                task.add_done_callback(agent_tasks.discard)
            await asyncio.sleep(0.5)
    finally:
        for task in agent_tasks:
            task.cancel()
        if agent_tasks:
            await asyncio.gather(*agent_tasks, return_exceptions=True)


async def run():
    agent_worker = asyncio.create_task(run_agent_worker())
    try:
        while True:
            for job_id in await pending_jobs():
                try:
                    await asyncio.wait_for(ingest(job_id),timeout=840)
                except Exception as exc:
                    logger.warning('Ingestion failed: job=%s category=%s',job_id,type(exc).__name__)
            for job_id in await pending_maintenance():
                try:
                    await maintain(job_id)
                except Exception as exc:
                    logger.warning('Maintenance failed: job=%s category=%s', job_id, type(exc).__name__)
            await asyncio.sleep(3)
    finally:
        agent_worker.cancel()
        await asyncio.gather(agent_worker, return_exceptions=True)
        await engine.dispose()


async def run_agent_safely(run_id):
    from app.application.chat import execute_agent_run
    try:
        await execute_agent_run(run_id)
    except Exception as exc:
        logger.warning('Agent worker failed: run=%s category=%s', run_id, type(exc).__name__)


async def pending_maintenance():
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        return list((await db.scalars(select(MaintenanceJob.id).where(or_(
            MaintenanceJob.status == 'queued',
            and_(MaintenanceJob.status == 'retrying', MaintenanceJob.updated_at < now-timedelta(seconds=15)),
            and_(MaintenanceJob.status == 'processing', MaintenanceJob.updated_at < now-timedelta(minutes=15))
        )).order_by(MaintenanceJob.created_at).limit(20))).all())

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(run())
    except KeyboardInterrupt: pass
