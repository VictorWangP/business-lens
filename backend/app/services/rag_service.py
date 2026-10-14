"""Citation projection at the authorized retrieval boundary."""
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
        nodes = await retriever.ainvoke(query)
        return RetrievalCitations([CitationItem(id=n.id, chunk_id=n.id,
                            doc_id=n.metadata['doc_id'], doc_name=n.metadata['filename'],
                            chunk_index=n.metadata['chunk_index'], content=n.page_content,
                            score=n.metadata['score'], pages=n.metadata.get('pages', []),
                            headings=n.metadata.get('headings', []), version=n.metadata['version'],
                            retrieval_warning='；'.join(retriever.diagnostics.get('warnings', []))) for n in nodes],
                            retriever.diagnostics.get('warnings', []))
