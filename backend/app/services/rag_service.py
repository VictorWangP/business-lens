"""Compatibility facade. All retrieval is implemented by a LlamaIndex retriever."""
from app.retrieval.retriever import KnowledgeRetriever
from app.schemas.chat import CitationItem

class RetrievalCitations(list):
    def __init__(self, items, warnings):
        super().__init__(items)
        self.warnings = warnings

class RAGService:
    @staticmethod
    async def query_knowledge_bases(user_id, kb_ids, query, top_k=6):
        retriever = KnowledgeRetriever(user_id, kb_ids, top_k)
        nodes = await retriever.aretrieve(query)
        return RetrievalCitations([CitationItem(id=n.node.node_id, chunk_id=n.node.node_id,
                            doc_id=n.node.metadata['doc_id'], doc_name=n.node.metadata['filename'],
                            chunk_index=n.node.metadata['chunk_index'], content=n.node.text,
                            score=n.score, pages=n.node.metadata.get('pages', []),
                            headings=n.node.metadata.get('headings', []), version=n.node.metadata['version'],
                            retrieval_warning='；'.join(retriever.diagnostics.get('warnings', []))) for n in nodes],
                            retriever.diagnostics.get('warnings', []))
