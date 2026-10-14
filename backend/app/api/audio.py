import json
import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.config import AppConfig
from app.security.auth import get_current_user
from app.services.audio_service import AudioService
from app.config import settings
from app.infrastructure.credentials import decrypt

router = APIRouter(prefix="/audio", tags=["语音交互"])
logger = logging.getLogger(__name__)

@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        api_base = settings.STT_API_BASE or 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        api_key = settings.STT_API_KEY
        if not api_key:
            config = await db.scalar(select(AppConfig).where(
                AppConfig.user_id == current_user.id, AppConfig.config_key == 'model_setting'))
            value = json.loads(config.config_value or '{}') if config else {}
            default_id = value.get('default_model')
            model = next((item for item in value.get('available_models', []) if item.get('id') == default_id), None)
            if model:
                base_url = (model.get('base_url') or '').rstrip('/')
                provider = (model.get('provider') or '').lower()
                if not any(token in base_url.lower() for token in ('dashscope', 'aliyuncs.com')) and not any(token in provider for token in ('百炼', '阿里云', 'aliyun')):
                    raise ValueError('请将默认对话模型配置为百炼模型，或单独配置 STT_API_KEY')
                api_base = base_url or api_base
                api_key = decrypt(model.get('api_key') or '')
        text = await AudioService.transcribe_audio(file, api_base=api_base, api_key=api_key)
        return {"text": text}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception('百炼语音识别调用失败（%s）', type(exc).__name__)
        raise HTTPException(502, '语音识别服务调用失败')

