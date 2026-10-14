import json
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.models.user import User
from app.models.config import AppConfig
from app.schemas.config import (
    AppConfigsResponse, WelcomeConfig, NextQuestionsConfig, 
    VoiceTTSConfig, VoiceSTTConfig, ModelSettingConfig, 
    FrequentQuestionsConfig, UpdateConfigPayload, ModelItem, ProviderRequest
)
from app.security.auth import get_current_user
from app.infrastructure.credentials import encrypt, decrypt
from app.services.model_provider import list_provider_models
from app.api.frequent import reset_required
from app.services.frequent_service import skip_unfinished

router = APIRouter(prefix="/settings", tags=["应用配置"])

async def saved_model_key(db, user_id, model_id, base_url):
    cfg = await db.scalar(select(AppConfig).where(AppConfig.user_id == user_id, AppConfig.config_key == 'model_setting'))
    models = json.loads(cfg.config_value or '{}').get('available_models', []) if cfg else []
    item = next((m for m in models if m['id'] == model_id), None)
    if not item or not item.get('api_key'):
        raise ValueError('未找到已保存的 API Key，请重新输入')
    if (item.get('base_url') or '').rstrip('/') != base_url.rstrip('/'):
        raise ValueError('更改 Base URL 后请重新输入 API Key')
    return item['api_key']

@router.post('/model-provider/models')
@router.post('/model-provider/test')
async def inspect_model_provider(payload: ProviderRequest, current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    try:
        key = payload.api_key or ''
        if key == '********':
            key = decrypt(await saved_model_key(db, current_user.id, payload.credential_model_id, payload.base_url))
        models = await list_provider_models(payload.base_url, key)
        return {'models': models, 'message': f'连接成功，模型列表接口返回 {len(models)} 个模型'}
    except ValueError as exc:
        raise HTTPException(422, str(exc))

@router.get("/app-config", response_model=AppConfigsResponse)
async def get_app_configs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AppConfig).where(AppConfig.user_id == current_user.id)
    res = await db.execute(stmt)
    configs = res.scalars().all()
    config_map = {c.config_key: (c.is_enabled, json.loads(c.config_value or "{}")) for c in configs}

    # 组装 6 张卡片的配置
    w_enabled, w_val = config_map.get("welcome_setting", (True, {}))
    welcome_cfg = WelcomeConfig(
        is_enabled=w_enabled,
        greeting=w_val.get("greeting", "你好"),
        assistant_name=w_val.get("assistant_name", "我是经管之星·AI问数助手"),
        description=w_val.get("description", "欢迎使用智能AI问数，您可以向我咨询经营数据、报表分析相关问题。"),
        questions=w_val.get("questions", [
            "各产品线销售情况",
            "北京的产品线收入情况",
            "深圳的产品销售情况"
        ])
    )

    nq_enabled, nq_val = config_map.get("next_questions", (True, {}))
    next_q_cfg = NextQuestionsConfig(
        is_enabled=nq_enabled,
        count=nq_val.get("count", 3)
    )

    tts_enabled, tts_val = config_map.get("voice_tts", (False, {}))
    voice_tts_cfg = VoiceTTSConfig(
        is_enabled=tts_enabled,
        voice_name=tts_val.get("voice_name", "zh-CN-XiaoxiaoNeural"),
        speed=tts_val.get("speed", 1.0)
    )

    stt_enabled, stt_val = config_map.get("voice_stt", (False, {}))
    voice_stt_cfg = VoiceSTTConfig(
        is_enabled=stt_enabled,
        engine=stt_val.get("engine", "openai-compatible")
    )

    m_enabled, m_val = config_map.get("model_setting", (True, {}))
    raw_models = m_val.get("available_models", [m.model_dump() for m in ModelSettingConfig().available_models])
    processed_models = []
    for item in raw_models:
        if isinstance(item, dict):
            if "type" not in item:
                item["type"] = "embedding" if "embed" in item.get("id", "").lower() or item.get("id") == "bge-m3" else "llm"
            item = dict(item)
            item["api_key"] = "********" if item.get("api_key") else None
            processed_models.append(ModelItem(**item))
        elif isinstance(item, ModelItem):
            processed_models.append(item)

    model_cfg = ModelSettingConfig(
        is_enabled=m_enabled,
        default_model=m_val.get("default_model", ""),
        default_embedding_model=m_val.get("default_embedding_model"),
        temperature=float(m_val.get("temperature", 0.7)),
        available_models=processed_models
    )

    fq_enabled, fq_val = config_map.get("frequent_questions", (True, {}))
    freq_cfg = FrequentQuestionsConfig(
        is_enabled=fq_enabled,
        threshold=int(fq_val.get("threshold", 3)),
        reset_required=await reset_required(db, current_user.id)
    )

    return AppConfigsResponse(
        welcome_setting=welcome_cfg,
        next_questions=next_q_cfg,
        voice_tts=voice_tts_cfg,
        voice_stt=voice_stt_cfg,
        model_setting=model_cfg,
        frequent_questions=freq_cfg
    )

@router.put("/app-config/{config_key}/toggle")
async def toggle_config(
    config_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AppConfig).where(
        and_(AppConfig.user_id == current_user.id, AppConfig.config_key == config_key)
    )
    res = await db.execute(stmt)
    cfg = res.scalar_one_or_none()
    if not cfg:
        # 如果不存在则初始化
        cfg = AppConfig(user_id=current_user.id, config_key=config_key, is_enabled=True, config_value="{}")
        db.add(cfg)
    
    cfg.is_enabled = not cfg.is_enabled
    if config_key == 'frequent_questions' and not cfg.is_enabled:
        await skip_unfinished(db, current_user.id)
    await db.commit()
    return {"config_key": config_key, "is_enabled": cfg.is_enabled}

@router.put("/app-config/{config_key}")
async def update_config(
    config_key: str,
    payload: UpdateConfigPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AppConfig).where(
        and_(AppConfig.user_id == current_user.id, AppConfig.config_key == config_key)
    )
    res = await db.execute(stmt)
    cfg = res.scalar_one_or_none()
    if not cfg:
        cfg = AppConfig(user_id=current_user.id, config_key=config_key, is_enabled=True, config_value="{}")
        db.add(cfg)

    if payload.is_enabled is not None:
        cfg.is_enabled = payload.is_enabled
    if payload.config_value is not None:
        value = payload.config_value.copy()
        if config_key == 'frequent_questions':
            try:
                value = {'threshold': FrequentQuestionsConfig(**value).threshold}
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        if config_key == 'model_setting':
            try:
                value = ModelSettingConfig(**value).model_dump(exclude={'is_enabled'})
                ids = [m['id'] for m in value['available_models']]
                if len(ids) != len(set(ids)):
                    raise ValueError('模型 ID 不能重复')
                for model in value['available_models']:
                    key = model.get('api_key')
                    if key == '********':
                        model['api_key'] = await saved_model_key(db, current_user.id,
                            model.get('credential_model_id') or model['id'], model.get('base_url') or '')
                    elif key:
                        model['api_key'] = encrypt(key)
                    model.pop('credential_model_id', None)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        cfg.config_value = json.dumps(value, ensure_ascii=False)

    if config_key == 'frequent_questions' and not cfg.is_enabled:
        await skip_unfinished(db, current_user.id)
    await db.commit()
    return {"message": "配置更新成功", "config_key": config_key, "is_enabled": cfg.is_enabled}
