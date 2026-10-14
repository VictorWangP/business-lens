from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import engine
from app.infrastructure.telemetry import configure
import app.models
from app.api import auth, settings as app_settings, sessions, knowledge, memory, audio, chat, data_sources, runs, frequent, workspaces, feedback

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SECRET_KEY == 'development-only-change-before-deploy' or len(settings.SECRET_KEY.encode()) < 32:
        raise RuntimeError('请设置独立的 SECRET_KEY')
    from app.infrastructure.tokenization import encoding
    encoding()
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    async with engine.connect() as conn:
        version = await conn.scalar(text('SELECT version_num FROM alembic_version'))
        if version != '0001_langgraph':
            raise RuntimeError('请先执行 alembic upgrade head')
    yield
    await engine.dispose()

app = FastAPI(title=settings.PROJECT_NAME, version='2.0.0', lifespan=lifespan)
configure(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'], allow_headers=['Authorization', 'Content-Type'])
for module in (auth, app_settings, sessions, knowledge, memory, audio, chat, data_sources, runs, frequent, workspaces, feedback):
    app.include_router(module.router, prefix='/api')

@app.get('/api/health')
async def health():
    return {'status': 'ok', 'service': settings.PROJECT_NAME}

@app.get('/api/ready')
async def ready():
    from fastapi import HTTPException
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
        if settings.TASK_BACKEND == 'celery':
            from redis.asyncio import Redis
            async with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2) as redis:
                await redis.ping()
    except Exception:
        raise HTTPException(503, '数据库或任务队列不可用')
    return {'status': 'ready'}
