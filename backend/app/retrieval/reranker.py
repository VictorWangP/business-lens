"""Optional dedicated rerank endpoint using the common query/documents/results contract."""
import math
import httpx
from langchain_core.documents import Document
from app.config import settings

async def rerank(query: str, candidates: list[Document], top_k: int) -> list[Document]:
    if not settings.RERANK_API_URL or not candidates:
        return candidates[:top_k]
    headers = {'Authorization': 'Bearer ' + settings.RERANK_API_KEY} if settings.RERANK_API_KEY else {}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(settings.RERANK_API_URL, headers=headers,
            json={'model': settings.RERANK_MODEL, 'query': query, 'documents': [n.page_content for n in candidates], 'top_n': top_k})
        response.raise_for_status()
        results = response.json().get('results', [])
    seen, output = set(), []
    for item in results:
        index, score = item['index'], float(item['relevance_score'])
        if not isinstance(index, int) or index < 0 or index >= len(candidates) or index in seen or not math.isfinite(score):
            raise ValueError('重排接口返回无效索引或得分')
        seen.add(index)
        output.append(candidates[index].model_copy(update={'metadata': {**candidates[index].metadata, 'score': score}}))
    if not output:
        raise ValueError('重排接口未返回结果')
    return sorted(output, key=lambda n: n.metadata['score'], reverse=True)[:top_k]
