import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import jieba
from sqlalchemy import select, delete, update, or_, and_
from app.database import AsyncSessionLocal
from app.config import settings
from app.models.knowledge import Document, KnowledgeBase
from app.models.platform import IngestionJob, DocumentChunk
from app.infrastructure.embeddings import EmbeddingProvider
from app.infrastructure.storage import store
from app.ingestion.parser import parse_document
from app.infrastructure.vector_index import index
from app.infrastructure.credentials import decrypt
from app.ingestion.maintenance import queue_cleanup


async def write_vectors(chunks, vectors, profile):
    # A cancelled to_thread call keeps running. Settle it before scheduling cleanup.
    task = asyncio.create_task(asyncio.to_thread(index.upsert, chunks, vectors, profile))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def fail_batch(db, job, error):
    jobs = list((await db.scalars(select(IngestionJob).where(IngestionJob.batch_id == job.batch_id))).all()) if job.batch_id else [job]
    for member in jobs:
        member.status, member.error = 'failed', error
        member.embedding_config = ''
        doc = await db.get(Document, member.doc_id)
        if doc:
            doc.status, doc.error_msg = ('ready' if doc.active_version else 'failed'), error
            doc.progress = 100 if doc.active_version else 0
            await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id,
                DocumentChunk.version == member.version, DocumentChunk.version != doc.active_version))
        queue_cleanup(db, member.user_id, member.doc_id, member.version)
    if job.batch_id:
        await db.execute(update(KnowledgeBase).where(KnowledgeBase.index_batch_id == job.batch_id).values(index_batch_id=''))


async def activate(db, jobs):
    for member in jobs:
        doc = await db.get(Document, member.doc_id)
        if not doc:
            raise ValueError('迁移期间文档已删除')
        old_versions = set((await db.scalars(select(IngestionJob.version).where(
            IngestionJob.doc_id == doc.id, IngestionJob.version != member.version))).all())
        old_versions.update((await db.scalars(select(DocumentChunk.version).where(
            DocumentChunk.doc_id == doc.id, DocumentChunk.version != member.version))).all())
        if doc.active_version and doc.active_version != member.version:
            old_versions.add(doc.active_version)
        doc.active_version, doc.status, doc.progress = member.version, 'ready', 100
        doc.chunk_count = len((await db.scalars(select(DocumentChunk.id).where(DocumentChunk.doc_id == doc.id,
            DocumentChunk.version == member.version))).all())
        doc.error_msg, member.status, member.error = '', 'ready', ''
        member.embedding_config = ''
        await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id, DocumentChunk.version != member.version))
        for version in old_versions:
            queue_cleanup(db, member.user_id, doc.id, version)
    if jobs[0].batch_id:
        await db.execute(update(KnowledgeBase).where(KnowledgeBase.index_batch_id == jobs[0].batch_id).values(index_batch_id=''))


async def ingest(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        # Atomic compare-and-update works on SQLite as well as PostgreSQL.
        claimed = await db.scalar(update(IngestionJob).where(IngestionJob.id == job_id,
            IngestionJob.attempts < 3, or_(IngestionJob.status.in_(['queued','retrying']),
            and_(IngestionJob.status == 'processing', IngestionJob.updated_at < now-timedelta(minutes=15))))
            .values(status='processing', attempts=IngestionJob.attempts+1, updated_at=now)
            .returning(IngestionJob.id))
        if not claimed:
            exhausted = await db.scalar(select(IngestionJob).where(IngestionJob.id == job_id,
                IngestionJob.attempts >= 3, IngestionJob.status.in_(['processing','retrying'])))
            if exhausted and exhausted.updated_at < now-timedelta(minutes=15):
                await fail_batch(db, exhausted, '处理进程中断，已达到重试次数，请重新建立索引')
                await db.commit()
            return
        job = await db.get(IngestionJob, job_id)
        doc = await db.get(Document, job.doc_id)
        if not doc or doc.user_id != job.user_id:
            job.status, job.error = 'failed', '文档已删除或归属无效'
            await db.commit()
            return
        doc.status, doc.progress, doc.error_msg = 'parsing', 10, ''
        await db.commit()
        user_id, doc_id, kb_id, filename, file_path, version, expected_hash = (
            job.user_id, doc.id, doc.kb_id, doc.filename, doc.file_path, job.version, job.content_hash)
        embedding_config = job.embedding_config
    phase = '解析'
    try:
        def parse_stored():
            with store.materialize(file_path) as path:
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                    raise ValueError('源文件校验失败，文件已变化')
                return parse_document(path, version)
        nodes, structure, markdown = await asyncio.to_thread(parse_stored)
        prefix = f'{user_id}/artifacts/{doc_id}/{version}'
        artifact = await asyncio.to_thread(store.put, f'{prefix}/document.json', json.dumps(structure, ensure_ascii=False).encode())
        await asyncio.to_thread(store.put, f'{prefix}/document.md', markdown.encode())
        phase = '嵌入配置'
        async with AsyncSessionLocal() as db:
            provider = EmbeddingProvider(json.loads(decrypt(embedding_config))) if embedding_config else await EmbeddingProvider.for_user(db, user_id)
            doc = await db.get(Document, doc_id)
            if not doc:
                queue_cleanup(db, user_id, doc_id, version)
                await db.commit()
                return
            doc.status, doc.progress = 'indexing', 60
            await db.commit()
        phase = '嵌入'
        vectors = await provider.embed([n.page_content for n in nodes])
        phase = '索引写入'
        if settings.DATABASE_URL.startswith('sqlite'):
            await write_vectors([{'id':n.id,'user_id':user_id,'kb_id':kb_id,'doc_id':doc_id,'version':version} for n in nodes], vectors, provider.profile)
        async with AsyncSessionLocal() as db:
            doc = await db.scalar(select(Document).where(Document.id == doc_id).with_for_update())
            job = await db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
            if not job or not doc or job.status != 'processing':
                queue_cleanup(db, user_id, doc_id, version)
                await db.commit()
                return
            await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id, DocumentChunk.version == version))
            for node, vector in zip(nodes, vectors, strict=True):
                metadata = {**node.metadata, 'filename': filename, 'embedding_dimension': len(vector)}
                db.add(DocumentChunk(id=node.id, user_id=user_id, kb_id=kb_id, doc_id=doc_id,
                                     version=version, chunk_index=node.metadata['chunk_index'], content=node.page_content,
                                     meta=metadata, embedding_profile=provider.profile, embedding=vector,
                                     keywords=' '.join(jieba.cut_for_search(node.page_content))))
            job.status, job.artifact_path, job.error = 'staged', artifact, ''
            doc.status, doc.progress = 'staged', 90
            await db.flush()
            members = list((await db.scalars(select(IngestionJob).where(IngestionJob.batch_id == job.batch_id)
                .with_for_update())).all()) if job.batch_id else [job]
            if all(member.status == 'staged' for member in members):
                await activate(db, members)
            await db.commit()
    except (Exception, asyncio.CancelledError) as exc:
        async with AsyncSessionLocal() as db:
            job = await db.get(IngestionJob, job_id)
            doc = await db.get(Document, doc_id)
            if job and doc:
                # Provider errors may contain secrets; persist a safe category, not response bodies.
                if job.status == 'failed':
                    queue_cleanup(db, user_id, doc_id, version)
                else:
                    job.error = phase + '失败：' + type(exc).__name__
                    if job.attempts >= 3:
                        await fail_batch(db, job, job.error)
                    else:
                        job.status = 'retrying'
                        doc.status, doc.error_msg = job.status, job.error
                await db.commit()
            else:
                queue_cleanup(db, user_id, doc_id, version)
                await db.commit()
        raise
