"""Run with python -m app.workers.local. One lightweight process; no Redis or Docker needed."""
import asyncio
import argparse
from contextlib import nullcontext
import logging
import signal
from datetime import UTC, datetime, timedelta
from app.database import engine
from app.application.chat import recover_expired_agent_runs, pending_agent_runs
from app.config import settings
from app.workers.frequent import run_frequent_worker, worker_lock

logger=logging.getLogger(__name__)


async def run_agent_worker():
    agent_tasks: set[asyncio.Task] = set()
    try:
        while True:
            await recover_expired_agent_runs()
            free_slots = max(0, settings.AGENT_WORKER_CONCURRENCY - len(agent_tasks))
            for run_id in await pending_agent_runs(free_slots) if settings.TASK_BACKEND == 'database' else []:
                task = asyncio.create_task(run_agent_safely(run_id))
                agent_tasks.add(task)
                task.add_done_callback(agent_tasks.discard)
            await asyncio.sleep(0.5)
    finally:
        for task in agent_tasks:
            task.cancel()
        if agent_tasks:
            await asyncio.gather(*agent_tasks, return_exceptions=True)


async def run(roles=None):
    consumers = {'agent': run_agent_worker, 'frequent': run_frequent_worker}
    selected = set(consumers if roles is None else roles)
    if not selected or selected - consumers.keys():
        raise ValueError('Worker roles must be agent or frequent')
    # Fail before starting any consumer if another frequent worker owns the lock.
    with worker_lock() if 'frequent' in selected else nullcontext():
        tasks = []
        try:
            tasks = [asyncio.create_task(consumer(), name=f'{role}-worker')
                     for role, consumer in consumers.items() if role in selected]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise RuntimeError('Worker consumer exited unexpectedly')
        finally:
            # Keep the frequent lock until all consumers have settled and writes ended.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await engine.dispose()


async def main(roles):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await run(roles)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


async def run_agent_safely(run_id):
    from app.application.chat import execute_agent_run
    try:
        await execute_agent_run(run_id)
    except Exception as exc:
        logger.warning('Agent worker failed: run=%s category=%s', run_id, type(exc).__name__)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description='Run background consumers in one process')
    parser.add_argument('--roles', nargs='+', choices=['agent', 'frequent'],
                        default=['agent', 'frequent'])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(main(args.roles))
    except (KeyboardInterrupt, asyncio.CancelledError): pass
