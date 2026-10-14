import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from app.config import settings
from app.database import Base
import app.models

def run_sync(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True, render_as_batch=connection.dialect.name == 'sqlite')
    with context.begin_transaction():
        context.run_migrations()

async def run_online():
    if settings.DATABASE_URL.startswith('sqlite'):
        from sqlalchemy.engine import make_url
        from pathlib import Path
        Path(make_url(settings.DATABASE_URL).database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_sync)
    await engine.dispose()

if context.is_offline_mode():
    raise RuntimeError('请使用在线迁移初始化新版数据库')
else:
    asyncio.run(run_online())
