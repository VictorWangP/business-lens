"""Unified worker scheduling, supervision and durable recovery."""
import asyncio
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.database import AsyncSessionLocal
from app.models.frequent import QuestionGroup, QuestionRecord
from app.workers import frequent, local
from test_frequent import providers, seed, message


@pytest.mark.asyncio
async def test_slow_frequent_does_not_block_other_consumers(monkeypatch):
    started = {role: asyncio.Event() for role in ('agent', 'frequent')}
    stopped = set()
    disposed = AsyncMock()

    def consumer(role):
        async def run():
            started[role].set()
            try:
                await asyncio.Event().wait()
            finally:
                # The lock must still be held while consumer shutdown finishes.
                with pytest.raises(RuntimeError, match='单实例'):
                    with frequent.worker_lock():
                        pass
                stopped.add(role)
        return run

    for role in started:
        monkeypatch.setattr(local, f'run_{role}_worker', consumer(role))

    async def dispose():
        assert stopped == set(started)
        await disposed()

    monkeypatch.setattr(local, 'engine', SimpleNamespace(dispose=dispose))
    task = asyncio.create_task(local.run())
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    disposed.assert_awaited_once()
    with frequent.worker_lock():
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [True, False])
async def test_consumer_exit_stops_siblings(monkeypatch, failure):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def agent():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def questions():
        await started.wait()
        if failure:
            raise RuntimeError('polling failed')

    monkeypatch.setattr(local, 'run_agent_worker', agent)
    monkeypatch.setattr(local, 'run_frequent_worker', questions)
    with pytest.raises(RuntimeError, match='polling failed' if failure else 'exited unexpectedly'):
        await asyncio.wait_for(local.run(['agent', 'frequent']), 5)
    assert stopped.is_set()
    with frequent.worker_lock():
        pass


@pytest.mark.asyncio
async def test_lock_conflict_prevents_all_consumers_starting(monkeypatch):
    agent = AsyncMock()
    monkeypatch.setattr(local, 'run_agent_worker', agent)
    with frequent.worker_lock():
        with pytest.raises(RuntimeError, match='单实例'):
            await local.run()
    agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_only_can_run_alongside_standalone_frequent(monkeypatch):
    started = asyncio.Event()

    async def agent():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(local, 'run_agent_worker', agent)
    with frequent.worker_lock():
        task = asyncio.create_task(local.run(['agent']))
        try:
            await asyncio.wait_for(started.wait(), 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unified_worker_recovers_interrupted_question(providers, monkeypatch):
    user, _, conversation, _, _ = await seed()
    mid = await message(user, conversation)
    started, completed = asyncio.Event(), asyncio.Event()
    original_process = frequent.process

    async def blocked_judge(*args):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(frequent.service, 'judge', blocked_judge)
    task = asyncio.create_task(local.run())
    try:
        await asyncio.wait_for(started.wait(), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with AsyncSessionLocal() as db:
        record = await db.get(QuestionRecord, mid)
        assert (record.status, record.attempts) == ('processing', 1)

    async def judge(*args):
        return True, None

    async def process(message_id):
        await original_process(message_id)
        completed.set()

    monkeypatch.setattr(frequent.service, 'judge', judge)
    monkeypatch.setattr(frequent, 'process', process)
    task = asyncio.create_task(local.run())
    try:
        await asyncio.wait_for(completed.wait(), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with AsyncSessionLocal() as db:
        record = await db.get(QuestionRecord, mid)
        assert (record.status, record.attempts) == ('completed', 2)
        assert await db.scalar(select(func.count()).select_from(QuestionGroup)) == 1


@pytest.mark.asyncio
async def test_cli_sigterm_cleans_up_and_releases_lock():
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'app.workers.local',
        cwd=Path(__file__).resolve().parents[1],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    async def wait_until_running():
        while True:
            assert process.returncode is None
            try:
                with frequent.worker_lock():
                    pass
            except RuntimeError:
                return
            await asyncio.sleep(0.05)

    try:
        await asyncio.wait_for(wait_until_running(), 15)
        process.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, stderr.decode()
        with frequent.worker_lock():
            pass
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
