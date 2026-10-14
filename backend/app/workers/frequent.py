"""Single local process: python -m app.workers.frequent (independent of ingestion)."""
import asyncio
import fcntl
import logging
from sqlalchemy import select, update
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.conversation import Message
from app.models.frequent import QuestionGroup, QuestionRecord
from app.infrastructure.embeddings import EmbeddingProvider
from app.services import frequent_service as service
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def recover():
    async with AsyncSessionLocal() as db:
        await db.execute(update(QuestionRecord).where(QuestionRecord.status == 'processing',
            QuestionRecord.attempts < service.MAX_ATTEMPTS).values(status='pending'))
        await db.execute(update(QuestionRecord).where(QuestionRecord.status.in_(['processing', 'pending']),
            QuestionRecord.attempts >= service.MAX_ATTEMPTS).values(status='failed', error_code='interrupted'))
        await db.commit()


async def process(message_id):
    try:
        async with AsyncSessionLocal() as db:
            record = await db.get(QuestionRecord, message_id)
            if not record or record.status != 'pending':
                return
            if await db.scalar(select(QuestionRecord.message_id).where(QuestionRecord.user_id == record.user_id,
                    QuestionRecord.error_code == service.PROFILE_CHANGED).limit(1)):
                return
            message = await db.get(Message, message_id)
            if not message or not (await service.config(db, record.user_id))[0] or not await service.valid_scope(db, record.user_id, record.kb_ids, record.source_ids):
                record.status, record.error_code = 'skipped', 'disabled_or_invalid_scope'
                await db.commit()
                return
            if record.attempts >= service.MAX_ATTEMPTS:
                record.status = 'failed'
                await db.commit()
                return
            # Claim once; duplicate invocations cannot increment or complete the record twice.
            claimed = await db.execute(update(QuestionRecord).where(QuestionRecord.message_id == message_id,
                QuestionRecord.status == 'pending').values(status='processing', attempts=QuestionRecord.attempts + 1))
            await db.commit()
            if not claimed.rowcount:
                return

        async with AsyncSessionLocal() as db:
            record = await db.get(QuestionRecord, message_id)
            if not record or record.status != 'processing':
                return
            message = await db.get(Message, message_id)
            provider = await EmbeddingProvider.for_user(db, record.user_id)
            profiles = set((await db.scalars(select(QuestionGroup.embedding_profile).where(QuestionGroup.user_id == record.user_id).distinct())).all())
            if profiles and profiles != {provider.profile}:
                record.status, record.error_code = 'pending', service.PROFILE_CHANGED
                record.attempts -= 1
                await db.commit()
                logger.warning('Frequent questions paused; reset required: user=%s', record.user_id)
                return
            active = select(QuestionRecord.group_id).where(QuestionRecord.user_id == record.user_id,
                QuestionRecord.scope_key == record.scope_key, QuestionRecord.status == 'completed')
            groups = list((await db.scalars(select(QuestionGroup).where(QuestionGroup.user_id == record.user_id,
                QuestionGroup.scope_key == record.scope_key, QuestionGroup.id.in_(active)))).all())
            exact_id = None
            if not service.RELATIVE_TIME.search(record.normalized_text):
                exact_ids = set((await db.scalars(select(QuestionRecord.group_id).where(
                    QuestionRecord.user_id == record.user_id, QuestionRecord.scope_key == record.scope_key,
                    QuestionRecord.status == 'completed', QuestionRecord.normalized_text == record.normalized_text))).all())
                exact_id = next((g.id for g in groups if g.id in exact_ids and not service.RELATIVE_TIME.search(g.representative_question)), None)
            cfg = None if exact_id else await LLMService.get_model_config(db, record.user_id)
            question, asked_at, user_id = message.content, message.created_at, record.user_id
            # End the read transaction before network calls; no SQL write lock is held.
            await db.commit()

        vector, eligible, group_id = None, True, exact_id
        if not exact_id:
            async def classify():
                vector = (await provider.embed([question], timeout=55, max_retries=0))[0]
                candidates = sorted(groups, key=lambda g: service.cosine(vector, g.embedding), reverse=True)[:service.TOP_K]
                eligible, group_id = await service.judge(cfg, question, asked_at, candidates)
                return vector, eligible, group_id
            vector, eligible, group_id = await asyncio.wait_for(classify(), timeout=service.MODEL_TIMEOUT)

        async with AsyncSessionLocal() as db:
            # Acquire the record's write lock before rechecking. A concurrent disable,
            # reset or deletion wins if it has already changed/removed this record.
            locked = await db.execute(update(QuestionRecord).where(QuestionRecord.message_id == message_id,
                QuestionRecord.status == 'processing').values(status='processing'))
            if not locked.rowcount:
                return
            record = await db.get(QuestionRecord, message_id)
            if not await db.get(Message, message_id) or not (await service.config(db, user_id))[0] or not await service.valid_scope(db, user_id, record.kb_ids, record.source_ids):
                record.status, record.error_code = 'skipped', 'disabled_or_invalid_scope'
            elif (await EmbeddingProvider.for_user(db, user_id)).profile != provider.profile:
                record.status, record.error_code = 'pending', service.PROFILE_CHANGED
                record.attempts -= 1
            elif not eligible:
                record.status, record.error_code = 'skipped', ''
            else:
                if group_id:
                    group = await db.get(QuestionGroup, group_id)
                    if not group or group.user_id != user_id or group.scope_key != record.scope_key:
                        raise ValueError('invalid_group_id')
                else:
                    group = QuestionGroup(user_id=user_id, scope_key=record.scope_key,
                        representative_question=question, representative_asked_at=asked_at,
                        embedding=vector, embedding_profile=provider.profile)
                    db.add(group)
                    await db.flush()
                    group_id = group.id
                record.group_id, record.status, record.error_code = group_id, 'completed', ''
            await db.commit()
    except Exception as exc:
        logger.warning('Frequent question failed: message=%s category=%s', message_id, type(exc).__name__)
        async with AsyncSessionLocal() as db:
            record = await db.get(QuestionRecord, message_id)
            if record and record.status == 'processing':
                record.status = 'failed' if record.attempts >= service.MAX_ATTEMPTS else 'pending'
                # Never persist provider credentials, question contents or raw errors.
                record.error_code = type(exc).__name__[:80]
                await db.commit()


async def pending_ids():
    async with AsyncSessionLocal() as db:
        paused = select(QuestionRecord.user_id).where(QuestionRecord.error_code == service.PROFILE_CHANGED)
        return list((await db.scalars(select(QuestionRecord.message_id).where(QuestionRecord.status == 'pending',
            QuestionRecord.user_id.not_in(paused)).order_by(QuestionRecord.created_at, QuestionRecord.message_id).limit(20))).all())


async def run():
    # Shared local storage ensures a second local/container worker fails before recovery.
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with (settings.STORAGE_DIR / 'frequent-worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('常问 worker 已运行；基础版只允许单实例') from exc
        try:
            await recover()
            while True:
                for message_id in await pending_ids():
                    await process(message_id)
                await asyncio.sleep(3)
        finally:
            await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
