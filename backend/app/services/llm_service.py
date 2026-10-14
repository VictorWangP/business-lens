"""Model configuration and real provider calls. There are no synthetic success responses."""
import json
from typing import AsyncGenerator
from openai import AsyncOpenAI
from sqlalchemy import select
from app.models.config import AppConfig
from app.infrastructure.credentials import decrypt

class ModelUnavailable(ValueError):
    pass

class LLMService:
    @staticmethod
    async def get_model_config(db, user_id: str, model_id: str | None = None, kind: str = 'llm') -> dict:
        cfg = await db.scalar(select(AppConfig).where(AppConfig.user_id == user_id, AppConfig.config_key == 'model_setting'))
        value = json.loads(cfg.config_value or '{}') if cfg else {}
        if cfg and not cfg.is_enabled:
            raise ModelUnavailable('模型功能已停用')
        label = '嵌入' if kind == 'embedding' else '对话'
        selected = model_id or value.get('default_embedding_model' if kind == 'embedding' else 'default_model')
        if not selected:
            raise ModelUnavailable(f'请先在模型设置中配置并选择{label}模型')
        item = next((m for m in value.get('available_models', []) if m.get('id') == selected), None)
        if not item:
            raise ModelUnavailable(f'所选{label}模型未配置，请在模型设置中添加')
        if (item.get('type') or 'llm') != kind:
            raise ModelUnavailable(f'所选模型不是 {kind} 模型')
        base = (item.get('base_url') or '').strip()
        if not base.startswith(('http://', 'https://')):
            raise ModelUnavailable('请在模型设置中配置有效的 Base URL')
        key = decrypt(item['api_key']) if item.get('api_key') else ''
        if not key.strip() or key in {'sk-mock-or-real-key', 'sk-...', 'your-api-key'}:
            raise ModelUnavailable('请在模型设置中配置有效的 API Key')
        return {'model_id': selected, 'model_name': item.get('name') or selected,
                'base_url': base.rstrip('/'), 'api_key': key,
                'temperature': float(value.get('temperature', 0.2))}

    @staticmethod
    async def stream_chat_completion(db, user_id, model_id, messages) -> AsyncGenerator[str, None]:
        cfg = await LLMService.get_model_config(db, user_id, model_id)
        async with AsyncOpenAI(base_url=cfg['base_url'], api_key=cfg['api_key'], timeout=60, max_retries=1) as client:
            stream = await client.chat.completions.create(model=cfg['model_id'], messages=messages,
                                                         temperature=cfg['temperature'], stream=True)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
