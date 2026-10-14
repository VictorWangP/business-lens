"""Initialize the independent LangGraph database and checkpoint store."""
import asyncio
import runpy
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if not (root / '.env').exists():
    runpy.run_path(str(root / 'scripts/init_env.py'))
from app.config import settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root, check=True)
async def initialize():
    async with AsyncSqliteSaver.from_conn_string(str(settings.STORAGE_DIR / 'checkpoints.sqlite')) as saver:
        await saver.setup()
asyncio.run(initialize())
print('新版应用数据库和 checkpoint 已就绪；请重新配置模型并导入业务资料。')
