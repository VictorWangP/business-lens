import json
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.database import get_db
from app.models.user import User
from app.models.business import SalesOrder
from app.models.config import AppConfig
from app.schemas.config import ModelSettingConfig
from app.schemas.auth import UserRegister, UserLogin, TokenResponse, UserOut
from app.security.auth import get_password_hash, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])

async def init_user_defaults(db: AsyncSession, user_id: str):
    """为新注册用户初始化应用配置；业务数据仅来自显式连接的数据源"""
    # 初始化 6 张卡片的默认配置
    default_configs = [
        ("welcome_setting", True, {
            "greeting": "你好",
            "assistant_name": "我是经管之星·AI问数助手",
            "description": "欢迎使用智能AI问数，您可以向我咨询经营数据、报表分析相关问题。",
            "questions": ["各产品线销售情况", "北京的产品线收入情况", "深圳的产品销售情况"]
        }),
        ("next_questions", True, {"count": 3}),
        ("voice_tts", False, {"voice_name": "zh-CN-XiaoxiaoNeural", "speed": 1.0}),
        ("voice_stt", False, {"engine": "openai-compatible"}),
        ("model_setting", True, ModelSettingConfig().model_dump(exclude={"is_enabled"})),
        ("frequent_questions", True, {"threshold": 3})
    ]
    for key, enabled, val in default_configs:
        config = AppConfig(
            user_id=user_id,
            config_key=key,
            is_enabled=enabled,
            config_value=json.dumps(val, ensure_ascii=False)
        )
        db.add(config)
    await db.commit()

@router.post("/register", response_model=TokenResponse)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(or_(User.username == payload.username, User.email == payload.email))
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户名或邮箱已被注册")

    hashed_pw = get_password_hash(payload.password)
    user = User(username=payload.username, email=payload.email, hashed_password=hashed_pw)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 初始化应用配置
    await init_user_defaults(db, user.id)

    token = create_access_token({"sub": user.id, "username": user.username})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.username == payload.username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")

    token = create_access_token({"sub": user.id, "username": user.username})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
