"""Back up and upgrade the local application database, preserving original business files."""
import json
import runpy
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if not (root / '.env').exists():
    runpy.run_path(str(root / 'scripts/init_env.py'))
from app.config import settings
from sqlalchemy.engine import make_url
from app.infrastructure.credentials import encrypt

if not settings.DATABASE_URL.startswith('sqlite'):
    raise SystemExit('此脚本仅升级本地 SQLite 应用数据库。')
path = Path(make_url(settings.DATABASE_URL).database).resolve()
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    backup = path.with_name(path.name + '.backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    backup.chmod(0o600)
    print('已备份应用数据库：' + str(backup))
subprocess.run([sys.executable, '-m', 'alembic', '-c', str(root/'alembic.ini'), 'upgrade', 'head'], check=True, cwd=root)
# Upgrade old plaintext model settings without printing any key.
with sqlite3.connect(path) as conn:
    for record_id, raw in conn.execute("SELECT id,config_value FROM app_configs WHERE config_key='model_setting'").fetchall():
        value = json.loads(raw or '{}')
        for model in value.get('available_models', []):
            key = model.get('api_key')
            if key and not key.startswith('enc:'):
                model['api_key'] = encrypt(key)
        if value.get('default_embedding_model') == 'chroma-builtin':
            value['default_embedding_model'] = ''
        conn.execute('UPDATE app_configs SET config_value=? WHERE id=?', (json.dumps(value, ensure_ascii=False),record_id))
print('本地数据库已就绪；旧文档需在知识库中重建索引。')
