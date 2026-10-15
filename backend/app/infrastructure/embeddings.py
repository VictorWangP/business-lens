import hashlib
import json
import math
from openai import AsyncOpenAI
from app.services.llm_service import LLMService

class EmbeddingProvider:
    def __init__(self, config: dict):
        self.config = config
        identity = json.dumps([config['base_url'], config['model_id']], ensure_ascii=False)
        self.profile = hashlib.sha256(identity.encode()).hexdigest()

    @classmethod
    async def for_user(cls, db, user_id):
        return cls(await LLMService.get_model_config(db, user_id, kind='embedding'))

    async def embed(self, texts: list[str], *, timeout=90, max_retries=2) -> list[list[float]]:
        vectors = []
        async with AsyncOpenAI(base_url=self.config['base_url'], api_key=self.config['api_key'], timeout=timeout, max_retries=max_retries) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start:start + 32]
                result = await client.embeddings.create(model=self.config['model_id'], input=batch)
                items = sorted(result.data, key=lambda item: item.index)
                if len(items) != len(batch) or [x.index for x in items] != list(range(len(batch))):
                    raise ValueError('嵌入接口返回数量或顺序无效')
                vectors.extend(item.embedding for item in items)
        if not vectors or not vectors[0] or any(len(v) != len(vectors[0]) or any(not math.isfinite(n) for n in v) or not any(v) for v in vectors):
            raise ValueError('嵌入接口返回了无效向量')
        return vectors
