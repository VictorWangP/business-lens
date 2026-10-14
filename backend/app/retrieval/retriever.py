import asyncio
import time
import jieba
from sqlalchemy import select, func, text, bindparam
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import TextNode, NodeWithScore, QueryBundle
from app.database import AsyncSessionLocal
from app.config import settings
from app.models.platform import DocumentChunk
from app.models.knowledge import Document
from app.infrastructure.embeddings import EmbeddingProvider
from app.retrieval.reranker import rerank
from app.infrastructure.vector_index import index


class KnowledgeRetriever(BaseRetriever):
    """Scoped hybrid retrieval; model failures explicitly degrade to lexical search."""
    def __init__(self, user_id: str, kb_ids: list[str], top_k: int = 6,
                 mode: str = 'hybrid', min_similarity: float | None = None):
        super().__init__()
        if mode not in {'hybrid', 'keyword', 'vector'}:
            raise ValueError('无效检索模式')
        self.user_id, self.kb_ids, self.top_k = user_id, kb_ids, min(max(top_k, 1), 12)
        self.mode = mode
        self.min_similarity = settings.RETRIEVAL_MIN_SIMILARITY if min_similarity is None else min_similarity
        self.diagnostics = {}

    def _retrieve(self, query_bundle: QueryBundle):
        raise RuntimeError('请使用 aretrieve，避免在事件循环中同步检索')

    async def lexical(self, db, base, query):
        tokens = list(dict.fromkeys(t for t in jieba.cut_for_search(query) if any(c.isalnum() for c in t)))[:32]
        if not tokens:
            return []
        if db.bind.dialect.name == 'postgresql':
            terms = func.plainto_tsquery('simple', ' '.join(tokens))
            tsv = func.to_tsvector('simple', DocumentChunk.keywords)
            return list((await db.scalars(base.where(tsv.op('@@')(terms))
                .order_by(func.ts_rank(tsv, terms).desc()).limit(40))).all())
        match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in tokens)
        stmt = text("""SELECT c.id FROM chunk_fts
            JOIN document_chunks c ON c.rowid=chunk_fts.rowid
            JOIN documents d ON d.id=c.doc_id
            WHERE chunk_fts MATCH :match AND c.user_id=:uid AND d.user_id=:uid
            AND c.kb_id IN :kbs AND c.version=d.active_version
            ORDER BY bm25(chunk_fts) LIMIT 40""").bindparams(bindparam('kbs', expanding=True))
        ids = list((await db.scalars(stmt, {'match': match, 'uid': self.user_id, 'kbs': self.kb_ids})).all())
        rows = {r.id: r for r in (await db.scalars(base.where(DocumentChunk.id.in_(ids)))).all()}
        return [rows[key] for key in ids if key in rows]

    async def semantic(self, db, base, profile, query):
        provider = await EmbeddingProvider.for_profile(db, self.user_id, profile)
        vector = (await provider.embed([query]))[0]
        scoped = base.where(DocumentChunk.embedding_profile == profile)
        dimension = func.vector_dims(DocumentChunk.embedding) if db.bind.dialect.name == 'postgresql' else func.json_array_length(DocumentChunk.embedding)
        if await db.scalar(scoped.with_only_columns(DocumentChunk.id).where(dimension != len(vector)).limit(1)):
            raise ValueError('向量维度与索引不一致，请修复或重建索引')
        if db.bind.dialect.name == 'postgresql':
            distance = DocumentChunk.embedding.cosine_distance(vector)
            rows = list((await db.scalars(scoped.where(distance <= 1-self.min_similarity)
                .order_by(distance).limit(40))).all())
            return rows, {r.id: None for r in rows}
        versions = list((await db.scalars(scoped.with_only_columns(DocumentChunk.version).distinct())).all())
        hits = await asyncio.to_thread(index.query_scored, profile, vector, self.user_id, self.kb_ids, versions, 40)
        # A populated SQL index with no Chroma candidates means the physical index needs repair.
        if not hits:
            raise ValueError('向量索引缺失，请修复索引')
        similarities = {key: similarity for key, similarity in hits if similarity >= self.min_similarity}
        rows = {r.id: r for r in (await db.scalars(scoped.where(DocumentChunk.id.in_(similarities)))).all()}
        return [rows[key] for key in similarities if key in rows], similarities

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        started = time.monotonic()
        self.diagnostics = {'requested_mode': self.mode, 'warnings': [], 'vector_candidates': 0,
            'keyword_candidates': 0, 'min_similarity': self.min_similarity, 'score_type': 'rrf', 'profiles': 0}
        if not self.kb_ids or not query_bundle.query_str.strip():
            return []
        async with AsyncSessionLocal() as db:
            base = select(DocumentChunk).join(Document, Document.id == DocumentChunk.doc_id).where(
                DocumentChunk.user_id == self.user_id, Document.user_id == self.user_id,
                DocumentChunk.kb_id.in_(self.kb_ids), DocumentChunk.version == Document.active_version)
            profiles = list((await db.scalars(base.with_only_columns(DocumentChunk.embedding_profile).distinct())).all())
            self.diagnostics['profiles'] = len(profiles)
            lexical_rows = await self.lexical(db, base, query_bundle.query_str) if self.mode != 'vector' else []
            rankings, similarities = [], {}
            for profile in profiles if self.mode != 'keyword' else []:
                try:
                    rows, values = await self.semantic(db, base, profile, query_bundle.query_str)
                    rankings.append(rows)
                    similarities.update(values)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, ValueError) else '嵌入或向量服务不可用：' + type(exc).__name__
                    if self.mode == 'vector':
                        raise ValueError(message) from exc
                    self.diagnostics['warnings'].append(message + '；该模型分组使用关键词检索')
            vector_count = sum(len(r) for r in rankings)
            self.diagnostics.update(vector_candidates=vector_count, keyword_candidates=len(lexical_rows))
            self.diagnostics['effective_mode'] = ('hybrid' if vector_count and lexical_rows else
                'vector' if vector_count else 'keyword' if lexical_rows else 'empty')
            scores, candidates, sources = {}, {}, {}
            for kind, ranking in [('vector', r) for r in rankings] + [('keyword', lexical_rows)]:
                for rank, row in enumerate(ranking, 1):
                    scores[row.id] = scores.get(row.id, 0) + 1 / (60 + rank)
                    candidates[row.id] = row
                    sources.setdefault(row.id, []).append(kind)
            chosen = sorted(scores, key=scores.get, reverse=True)[:40]
            nodes = [NodeWithScore(node=TextNode(id_=key, text=candidates[key].content,
                metadata={**candidates[key].meta, 'doc_id': candidates[key].doc_id,
                    'kb_id': candidates[key].kb_id, 'version': candidates[key].version,
                    'chunk_index': candidates[key].chunk_index, 'retrieval_sources': sources[key],
                    'vector_similarity': similarities.get(key)}), score=scores[key]) for key in chosen]
            try:
                result = await rerank(query_bundle.query_str, nodes, self.top_k)
                if settings.RERANK_API_URL and nodes:
                    self.diagnostics['score_type'] = 'reranker'
            except Exception as exc:
                self.diagnostics['warnings'].append('重排服务不可用，使用融合排序：' + type(exc).__name__)
                result = nodes[:self.top_k]
            self.diagnostics.update(returned=len(result), elapsed_ms=round((time.monotonic()-started)*1000, 1))
            return result


async def read_chunk(user_id: str, kb_ids: list[str], chunk_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(DocumentChunk).join(Document, Document.id == DocumentChunk.doc_id).where(
            DocumentChunk.id == chunk_id, DocumentChunk.user_id == user_id,
            Document.user_id == user_id, DocumentChunk.kb_id.in_(kb_ids),
            DocumentChunk.version == Document.active_version))
        if not row:
            raise ValueError('切片不存在、已更新或无权访问')
        neighbors = (await db.scalars(select(DocumentChunk).where(DocumentChunk.doc_id == row.doc_id,
            DocumentChunk.user_id == user_id, DocumentChunk.version == row.version,
            DocumentChunk.chunk_index.between(row.chunk_index-1, row.chunk_index+1)).order_by(DocumentChunk.chunk_index))).all()
        return [{'chunk_id': r.id, 'doc_id': r.doc_id, 'version': r.version, 'content': r.content, **r.meta} for r in neighbors]
