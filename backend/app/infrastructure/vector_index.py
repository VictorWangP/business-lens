"""Explicit-vector Chroma adapter: never downloads or selects an implicit embedding model."""
from functools import lru_cache
import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import settings

@lru_cache(maxsize=4)
def client(path: str):
    return chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))

class VectorIndex:
    def collection(self, profile: str, dimension: int):
        return client(str(settings.CHROMA_PERSIST_DIR)).get_or_create_collection(
            name=f'p_{profile[:40]}_d{dimension}', embedding_function=None, metadata={'hnsw:space':'cosine'})

    def upsert(self, chunks, vectors, profile):
        col=self.collection(profile,len(vectors[0]))
        for start in range(0,len(chunks),500):
            batch=chunks[start:start+500]
            col.upsert(ids=[n['id'] for n in batch], embeddings=vectors[start:start+500],
                metadatas=[{'user_id':n['user_id'],'kb_id':n['kb_id'],'version':n['version'],'doc_id':n['doc_id']} for n in batch])

    def query(self, profile, vector, user_id, kb_ids, versions, top_k=40):
        return [key for key, _ in self.query_scored(profile, vector, user_id, kb_ids, versions, top_k)]

    def query_scored(self, profile, vector, user_id, kb_ids, versions, top_k=40):
        col=self.collection(profile,len(vector))
        count=col.count()
        if not count: return []
        result=col.query(query_embeddings=[vector], n_results=min(top_k,count),
            where={'$and':[{'user_id':user_id},{'kb_id':{'$in':kb_ids}},{'version':{'$in':versions}}]}, include=['distances'])
        return list(zip(result['ids'][0], [1-float(d) for d in result['distances'][0]])) if result['ids'] else []

    def delete_document(self, doc_id, version=None):
        db=client(str(settings.CHROMA_PERSIST_DIR))
        scope = {'doc_id':doc_id} if version is None else {'$and':[{'doc_id':doc_id},{'version':version}]}
        for col in db.list_collections():
            db.get_collection(col.name,embedding_function=None).delete(where=scope)

    def ids(self, profile, dimension, user_id, kb_id, versions):
        col = self.collection(profile, dimension)
        return set(col.get(where={'$and':[{'user_id':user_id},{'kb_id':kb_id},
            {'version':{'$in':versions}}]}, include=[])['ids']) if versions else set()

    def prune(self, user_id, kb_id, valid_ids, protected_versions):
        removed = 0
        db = client(str(settings.CHROMA_PERSIST_DIR))
        for entry in db.list_collections():
            col = db.get_collection(entry.name, embedding_function=None)
            result = col.get(where={'$and':[{'user_id':user_id},{'kb_id':kb_id}]}, include=['metadatas'])
            stale = [key for key, meta in zip(result['ids'], result['metadatas'], strict=True)
                if key not in valid_ids and meta['version'] not in protected_versions]
            for start in range(0, len(stale), 500):
                col.delete(ids=stale[start:start+500])
            removed += len(stale)
        return removed

index=VectorIndex()
