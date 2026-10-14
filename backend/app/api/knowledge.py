import os
import shutil
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from app.database import get_db, AsyncSessionLocal
from app.config import settings
from app.models.user import User
from app.models.knowledge import KnowledgeBase, Document
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseOut, DocumentOut, RetrievalProbe
from app.security.auth import get_current_user
from app.models.platform import IngestionJob, DocumentChunk, MaintenanceJob
from app.infrastructure.storage import store
from app.workers.dispatch import enqueue_document
from sqlalchemy import delete, update
from app.ingestion.maintenance import queue_cleanup
from app.infrastructure.embeddings import EmbeddingProvider
from app.infrastructure.credentials import encrypt
import json
import uuid
import hashlib
import asyncio
import logging
from app.infrastructure.vector_index import index
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["知识库与文档"])

@router.get("/bases", response_model=List[KnowledgeBaseOut])
async def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.user_id == current_user.id
    ).order_by(KnowledgeBase.created_at.desc())
    res = await db.execute(stmt)
    kbs = res.scalars().all()

    output = []
    for kb in kbs:
        count_stmt = select(func.count(Document.id)).where(Document.kb_id == kb.id)
        count_res = await db.execute(count_stmt)
        doc_count = count_res.scalar_one() or 0
        output.append(KnowledgeBaseOut(
            id=kb.id,
            name=kb.name,
            description=kb.description or "",
            document_count=doc_count,
            created_at=kb.created_at,
            index_batch_id=kb.index_batch_id
        ))
    return output

@router.post("/bases", response_model=KnowledgeBaseOut)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not payload.name.strip():
        raise HTTPException(422, '知识库名称不能为空')
    kb = KnowledgeBase(
        user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description or ""
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description or "",
        document_count=0,
        created_at=kb.created_at
    )

@router.delete("/bases/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(KnowledgeBase).where(
        and_(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    kb = res.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == kb_id,
        KnowledgeBase.index_batch_id == '').values(index_batch_id='').returning(KnowledgeBase.id)):
        raise HTTPException(409, '全库重建期间不能删除知识库')
    documents = (await db.scalars(select(Document).where(Document.kb_id == kb_id))).all()
    for doc in documents:
        queue_cleanup(db, current_user.id, doc.id, original=doc.file_path)

    await db.execute(delete(DocumentChunk).where(DocumentChunk.kb_id == kb_id, DocumentChunk.user_id == current_user.id))
    doc_ids = list((await db.scalars(select(Document.id).where(Document.kb_id == kb_id))).all())
    await db.delete(kb)
    await db.commit()
    for doc_id in doc_ids:
        await cleanup_vectors(doc_id)
    return {"message": "知识库已删除", "kb_id": kb_id}

@router.get("/bases/{kb_id}/documents", response_model=List[DocumentOut])
async def list_documents(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(
        and_(Document.kb_id == kb_id, Document.user_id == current_user.id)
    ).order_by(Document.created_at.desc())
    res = await db.execute(stmt)
    docs = res.scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]

@router.post("/bases/{kb_id}/documents/upload", response_model=DocumentOut)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 校验知识库归属
    kb_stmt = select(KnowledgeBase).where(
        and_(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == current_user.id)
    )
    kb_res = await db.execute(kb_stmt)
    if not kb_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == kb_id,
        KnowledgeBase.index_batch_id == '').values(index_batch_id='').returning(KnowledgeBase.id)):
        raise HTTPException(409, '全库重建期间不能上传文档')

    filename = Path(file.filename or '').name
    if not filename or filename != file.filename or Path(filename).suffix.lower() not in {'.pdf', '.docx', '.pptx', '.xlsx', '.html', '.md', '.txt', '.csv'}:
        raise HTTPException(422, '文件名称或格式无效')
    content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, '文件为空或超过上传大小限制')
    doc_id = str(uuid.uuid4())
    dest_file_path = await asyncio.to_thread(store.put, f'{current_user.id}/originals/{doc_id}/{filename}', content)
    file_size = len(content)

    doc = Document(
        id=doc_id,
        user_id=current_user.id,
        kb_id=kb_id,
        filename=filename,
        file_path=str(dest_file_path),
        file_size=file_size,
        status="queued",
        progress=0.0
    )
    db.add(doc)
    await db.flush()

    job = IngestionJob(user_id=current_user.id, doc_id=doc.id, content_hash=hashlib.sha256(content).hexdigest())
    db.add(job)
    await db.commit()
    await db.refresh(doc)
    try:
        await asyncio.to_thread(enqueue_document, job.id)
    except Exception:
        pass  # Persisted queued jobs are dispatched by beat after broker recovery.

    return DocumentOut.model_validate(doc)

@router.get("/documents/{doc_id}/status", response_model=DocumentOut)
async def get_document_status(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(
        and_(Document.id == doc_id, Document.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocumentOut.model_validate(doc)


@router.post('/documents/{doc_id}/reindex')
async def reindex_document(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == current_user.id).with_for_update())
    if not doc:
        raise HTTPException(404, '文档不存在')
    if not await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id,
        KnowledgeBase.index_batch_id == '').values(index_batch_id='').returning(KnowledgeBase.id)):
        raise HTTPException(409, '知识库已有全库重建任务')
    pending = await db.scalar(select(IngestionJob.id).where(IngestionJob.doc_id == doc_id, IngestionJob.status.in_(['queued', 'processing', 'retrying', 'staged'])))
    if pending:
        raise HTTPException(409, '文档已有待处理任务')
    try:
        content = await asyncio.to_thread(store.read, doc.file_path)
    except Exception:
        raise HTTPException(422, '原始文件不可访问，请检查存储或重新上传')
    job = IngestionJob(user_id=current_user.id, doc_id=doc_id, content_hash=hashlib.sha256(content).hexdigest())
    db.add(job)
    doc.status, doc.progress, doc.error_msg = 'queued', 0, ''
    await db.commit()
    return {'job_id': job.id, 'status': job.status}


@router.delete('/documents/{doc_id}', status_code=204)
async def delete_document(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == current_user.id).with_for_update())
    if not doc:
        raise HTTPException(404, '文档不存在')
    if not await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id,
        KnowledgeBase.index_batch_id == '').values(index_batch_id='').returning(KnowledgeBase.id)):
        raise HTTPException(409, '全库重建期间不能删除文档')
    queue_cleanup(db, current_user.id, doc.id, original=doc.file_path)
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
    await db.execute(delete(IngestionJob).where(IngestionJob.doc_id == doc_id))
    await db.delete(doc)
    await db.commit()
    await cleanup_vectors(doc_id)


@router.get('/chunks/{chunk_id}')
async def get_chunk(chunk_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(DocumentChunk).join(Document, Document.id == DocumentChunk.doc_id).where(
        DocumentChunk.id == chunk_id, DocumentChunk.user_id == current_user.id, DocumentChunk.version == Document.active_version))
    if not row:
        raise HTTPException(404, '引用已更新或不存在')
    return {'id': row.id, 'content': row.content, 'metadata': row.meta, 'version': row.version}


@router.get('/documents/{doc_id}/download')
async def download_document(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from fastapi.responses import Response
    from urllib.parse import quote
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == current_user.id))
    if not doc:
        raise HTTPException(404, '文档不存在')
    try:
        content = await asyncio.to_thread(store.read, doc.file_path)
    except Exception:
        raise HTTPException(404, '原始文件不可访问')
    return Response(content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(doc.filename)})


async def cleanup_vectors(doc_id):
    if settings.DATABASE_URL.startswith('sqlite'):
        try:
            await asyncio.to_thread(index.delete_document, doc_id)
        except Exception:
            # SQL ownership/active-version filters already make deleted evidence inaccessible.
            logger.warning('Vector cleanup pending: document=%s', doc_id)


async def owned_base(db, user_id, kb_id):
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id))
    if not kb:
        raise HTTPException(404, '知识库不存在')
    return kb


@router.patch('/bases/{kb_id}', response_model=KnowledgeBaseOut)
async def edit_base(kb_id: str, payload: KnowledgeBaseCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await owned_base(db, current_user.id, kb_id)
    if not payload.name.strip():
        raise HTTPException(422, '知识库名称不能为空')
    kb.name, kb.description = payload.name.strip(), payload.description
    await db.commit()
    count = await db.scalar(select(func.count(Document.id)).where(Document.kb_id == kb_id))
    return KnowledgeBaseOut(id=kb.id, name=kb.name, description=kb.description,
        created_at=kb.created_at, document_count=count, index_batch_id=kb.index_batch_id)


@router.post('/bases/{kb_id}/reindex')
async def reindex_base(kb_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_base(db, current_user.id, kb_id)
    batch_id = str(uuid.uuid4())
    locked = await db.scalar(update(KnowledgeBase).where(KnowledgeBase.id == kb_id,
        KnowledgeBase.index_batch_id == '').values(index_batch_id=batch_id).returning(KnowledgeBase.id))
    if not locked:
        raise HTTPException(409, '知识库已有全库重建任务')
    pending = await db.scalar(select(IngestionJob.id).join(Document, Document.id == IngestionJob.doc_id).where(
        Document.kb_id == kb_id, IngestionJob.status.in_(['queued', 'retrying', 'processing', 'staged'])).limit(1))
    if pending:
        raise HTTPException(409, '请等待现有文档处理完成后再全库重建')
    docs = (await db.scalars(select(Document).where(Document.kb_id == kb_id))).all()
    if not docs:
        raise HTTPException(422, '知识库没有文档')
    try:
        provider = await EmbeddingProvider.for_user(db, current_user.id)
        snapshot = encrypt(json.dumps(provider.config))
        for doc in docs:
            content = await asyncio.to_thread(store.read, doc.file_path)
            db.add(IngestionJob(user_id=current_user.id, doc_id=doc.id, batch_id=batch_id,
                embedding_config=snapshot, content_hash=hashlib.sha256(content).hexdigest()))
            doc.status, doc.progress, doc.error_msg = 'queued', 0, ''
    except Exception:
        raise HTTPException(422, '无法提交重建：请检查嵌入模型配置和原始文件')
    await db.commit()
    return {'batch_id': batch_id, 'document_count': len(docs), 'model_id': provider.config['model_id'],
        'note': '全部文档完成后一起激活；失败时保留旧索引'}


@router.get('/bases/{kb_id}/jobs')
async def base_jobs(kb_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await owned_base(db, current_user.id, kb_id)
    jobs = (await db.scalars(select(IngestionJob).join(Document, Document.id == IngestionJob.doc_id).where(
        Document.kb_id == kb_id).order_by(IngestionJob.created_at.desc()).limit(100))).all()
    return {'batch_id': kb.index_batch_id, 'items': [dict(id=j.id, doc_id=j.doc_id, batch_id=j.batch_id,
        status=j.status, attempts=j.attempts, error=j.error, created_at=j.created_at, updated_at=j.updated_at) for j in jobs]}


@router.get('/documents/{doc_id}/chunks')
async def document_chunks(doc_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == current_user.id))
    if not doc:
        raise HTTPException(404, '文档不存在')
    scope = (DocumentChunk.doc_id == doc_id, DocumentChunk.version == doc.active_version)
    total = await db.scalar(select(func.count(DocumentChunk.id)).where(*scope))
    rows = (await db.scalars(select(DocumentChunk).where(*scope).order_by(DocumentChunk.chunk_index).offset(offset).limit(limit))).all()
    return {'total': total, 'version': doc.active_version, 'items': [dict(id=r.id, content=r.content,
        chunk_index=r.chunk_index, metadata=r.meta) for r in rows]}


@router.post('/bases/{kb_id}/search')
async def search_base(kb_id: str, payload: RetrievalProbe, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_base(db, current_user.id, kb_id)
    if not payload.query.strip():
        raise HTTPException(422, '检索问题不能为空')
    from app.retrieval.retriever import KnowledgeRetriever
    retriever = KnowledgeRetriever(current_user.id, [kb_id], payload.top_k, mode=payload.mode, min_similarity=payload.min_similarity)
    try:
        nodes = await retriever.ainvoke(payload.query)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {'items': [dict(chunk_id=n.id, content=n.page_content, score=n.metadata['score'],
        metadata=n.metadata) for n in nodes], 'diagnostics': retriever.diagnostics}


@router.post('/bases/{kb_id}/repair')
async def repair_base(kb_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_base(db, current_user.id, kb_id)
    job = MaintenanceJob(user_id=current_user.id, kind='repair', payload={'kb_id': kb_id})
    db.add(job)
    await db.commit()
    return {'job_id': job.id, 'status': job.status}


@router.get('/maintenance')
async def maintenance_jobs(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    jobs = (await db.scalars(select(MaintenanceJob).where(MaintenanceJob.user_id == current_user.id)
        .order_by(MaintenanceJob.created_at.desc()).limit(50))).all()
    return [dict(id=j.id, kind=j.kind, status=j.status, attempts=j.attempts, error=j.error,
        result=j.payload.get('result'), created_at=j.created_at) for j in jobs]


@router.post('/maintenance/{job_id}/retry')
async def retry_maintenance(job_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(MaintenanceJob).where(MaintenanceJob.id == job_id, MaintenanceJob.user_id == current_user.id))
    if not job:
        raise HTTPException(404, '维护任务不存在')
    if job.status != 'failed':
        raise HTTPException(409, '只有失败任务可以重新提交')
    job.status, job.attempts, job.error = 'queued', 0, ''
    await db.commit()
    return {'job_id': job.id, 'status': job.status}
