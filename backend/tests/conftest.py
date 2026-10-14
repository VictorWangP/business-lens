import os
import sys
import tempfile
from pathlib import Path
import pytest_asyncio
from cryptography.fernet import Fernet

TEST_ROOT = Path(tempfile.mkdtemp(prefix='rag-platform-tests-'))
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{TEST_ROOT}/app.db'
os.environ['STORAGE_DIR'] = str(TEST_ROOT / 'storage')
os.environ['SECRET_KEY'] = 'test-secret-only-not-for-production-123456'
os.environ['CREDENTIAL_KEY'] = Fernet.generate_key().decode()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest_asyncio.fixture(autouse=True)
async def database():
    from app.database import engine, Base
    import app.models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        from app.infrastructure.lexical_index import install
        await conn.run_sync(install)
    yield
    await engine.dispose()
