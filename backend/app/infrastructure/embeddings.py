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

    @classmethod
    async def for_profile(cls, db, user_id, profile):
        """Read old indexes with their configured model during a default-model migration."""
        from sqlalchemy import select
        from app.models.config import AppConfig
        try:
            provider = await cls.for_user(db, user_id)
            if provider.profile == profile:
                return provider
        except ValueError:
            pass
        cfg = await db.scalar(select(AppConfig).where(AppConfig.user_id == user_id, AppConfig.config_key == 'model_setting'))
        value = json.loads(cfg.config_value or '{}') if cfg else {}
        model_ids = list(dict.fromkeys([item['id'] for item in value.get('available_models', []) if item.get('type') == 'embedding']))
        for model_id in model_ids:
            try:
                provider = cls(await LLMService.get_model_config(db, user_id, model_id=model_id, kind='embedding'))
                if provider.profile == profile:
                    return provider
            except ValueError:
                continue
        raise ValueError('索引对应的嵌入模型未配置；请保留旧模型配置或重建索引')

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
