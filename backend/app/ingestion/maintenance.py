"""Durable, idempotent maintenance; deletion is limited to an exact document/version."""
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import select, update, or_, and_, text
from app.database import AsyncSessionLocal
from app.config import settings
from app.models.knowledge import Document, KnowledgeBase
from app.models.platform import MaintenanceJob, DocumentChunk, IngestionJob
from app.infrastructure.storage import store
from app.infrastructure.vector_index import index


def queue_cleanup(db, user_id, doc_id, version=None, original=None):
    db.add(MaintenanceJob(user_id=user_id, kind='cleanup', payload={
        'doc_id': doc_id, 'version': version, 'original': original}))


async def repair_index(user_id, kb_id):
    """Restore missing Chroma entries from committed SQL vectors; no embedding calls."""
    async with AsyncSessionLocal() as db:
        # Serialize resource mutations while taking the reconciliation snapshot.
        kb = await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user_id).values(index_batch_id=KnowledgeBase.index_batch_id).returning(KnowledgeBase.id))
        if not kb:
            return {'checked_chunks': 0, 'restored_vectors': 0, 'removed_vectors': 0}
        rows = (await db.scalars(select(DocumentChunk).join(Document, Document.id == DocumentChunk.doc_id).where(
            DocumentChunk.user_id == user_id, DocumentChunk.kb_id == kb_id,
            DocumentChunk.version == Document.active_version))).all()
        groups = defaultdict(list)
        for row in rows:
            groups[(row.embedding_profile, len(row.embedding))].append(row)
        missing, removed = 0, 0
        if settings.DATABASE_URL.startswith('sqlite'):
            for (profile, dimension), chunks in groups.items():
                present = await asyncio.to_thread(index.ids, profile, dimension, user_id, kb_id, list({r.version for r in chunks}))
                absent = [r for r in chunks if r.id not in present]
                missing += len(absent)
                if absent:
                    await asyncio.to_thread(index.upsert, [dict(id=r.id, user_id=r.user_id, kb_id=r.kb_id,
                        doc_id=r.doc_id, version=r.version) for r in absent], [r.embedding for r in absent], profile)
            protected = set((await db.scalars(select(IngestionJob.version).join(Document, Document.id == IngestionJob.doc_id).where(
                Document.kb_id == kb_id, IngestionJob.status.in_(['queued', 'retrying', 'processing', 'staged'])))).all())
            removed = await asyncio.to_thread(index.prune, user_id, kb_id, {r.id for r in rows}, protected)
            await db.execute(text("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')"))
        await db.commit()
        return {'checked_chunks': len(rows), 'restored_vectors': missing, 'removed_vectors': removed}


async def maintain(job_id):
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        claimed = await db.scalar(update(MaintenanceJob).where(MaintenanceJob.id == job_id, MaintenanceJob.attempts < 5, or_(
            MaintenanceJob.status.in_(['queued', 'retrying']),
            and_(MaintenanceJob.status == 'processing', MaintenanceJob.updated_at < now-timedelta(minutes=15))))
            .values(status='processing', attempts=MaintenanceJob.attempts+1, updated_at=now).returning(MaintenanceJob.id))
        if not claimed:
            exhausted = await db.get(MaintenanceJob, job_id)
            if exhausted and exhausted.attempts >= 5 and exhausted.status == 'processing' and exhausted.updated_at < now-timedelta(minutes=15):
                exhausted.status, exhausted.error = 'failed', '维护进程中断，已达到重试次数，请重新提交'
                await db.commit()
            return
        job = await db.get(MaintenanceJob, job_id)
        kind, payload, user_id = job.kind, job.payload, job.user_id
        await db.commit()
    try:
        if kind == 'repair':
            result = await repair_index(user_id, payload['kb_id'])
        elif kind == 'cleanup':
            doc_id, version = payload['doc_id'], payload.get('version')
            async with AsyncSessionLocal() as db:
                doc = await db.get(Document, doc_id)
                # Never delete a live document or its active version.
                if doc and (version is None or doc.active_version == version):
                    raise ValueError('维护任务试图清理有效文档版本')
                original_shared = payload.get('original') and await db.scalar(select(Document.id).where(
                    Document.file_path == payload['original']).limit(1))
            if settings.DATABASE_URL.startswith('sqlite'):
                await asyncio.to_thread(index.delete_document, doc_id, version)
            if payload.get('original') and not original_shared:
                await asyncio.to_thread(store.delete, payload['original'])
            await asyncio.to_thread(store.delete_artifacts, user_id, doc_id, version or '')
            result = {'cleaned': True}
        else:
            raise ValueError('未知维护任务类型')
        async with AsyncSessionLocal() as db:
            job = await db.get(MaintenanceJob, job_id)
            job.status, job.payload, job.error = 'ready', {**payload, 'result': result}, ''
            await db.commit()
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            job = await db.get(MaintenanceJob, job_id)
            job.status = 'failed' if job.attempts >= 5 else 'retrying'
            job.error = '维护失败：' + type(exc).__name__
            await db.commit()
        raise
