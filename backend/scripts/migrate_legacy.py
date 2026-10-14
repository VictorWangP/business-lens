"""Copy legacy SQLite application records into a migrated empty PostgreSQL database.
Run without --apply to inspect counts. Does not modify the source or import demo orders.
"""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from app.database import Base, engine
import app.models
from app.models.platform import IngestionJob
from app.infrastructure.credentials import encrypt
from app.infrastructure.storage import store

TABLES = ('users', 'business_workspaces', 'app_configs', 'knowledge_bases', 'conversations', 'documents',
          'messages', 'bookmarks', 'user_profiles', 'memory_facts')

async def migrate(path: Path, apply: bool):
    if not path.is_file():
        raise ValueError('旧数据库文件不存在')
    source = sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    existing = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        counts = {name: source.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in TABLES if name in existing}
        print(json.dumps({'application_records': counts, 'legacy_business': 'excluded', 'apply': apply}, ensure_ascii=False))
        if not apply:
            return
        if engine.dialect.name != 'postgresql':
            raise ValueError('迁移目标必须是已执行 Alembic 的 PostgreSQL')
        async with engine.begin() as conn:
            for name in TABLES:
                table = Base.metadata.tables[name]
                if await conn.scalar(select(func.count()).select_from(table)):
                    raise ValueError('目标应用表必须为空；请使用新数据库迁移，避免覆盖数据')
            for name in TABLES:
                if name not in existing:
                    continue
                table = Base.metadata.tables[name]
                for record in source.execute(f'SELECT * FROM "{name}"'):
                    row = {k: record[k] for k in record.keys() if k in table.c}
                    for col in table.c:
                        if col.name in row and row[col.name] is not None:
                            if str(col.type).startswith('DATETIME'):
                                row[col.name] = datetime.fromisoformat(row[col.name])
                            elif str(col.type) == 'BOOLEAN':
                                row[col.name] = bool(row[col.name])
                    if name == 'app_configs' and row['config_key'] == 'model_setting':
                        value = json.loads(row['config_value'] or '{}')
                        for model in value.get('available_models', []):
                            key = model.get('api_key')
                            if key and not key.startswith('enc:'):
                                model['api_key'] = encrypt(key)
                        if value.get('default_embedding_model') == 'chroma-builtin':
                            value['default_embedding_model'] = ''
                        row['config_value'] = json.dumps(value, ensure_ascii=False)
                    job = None
                    if name == 'documents':
                        original = Path(row['file_path']).resolve()
                        source_root = (path.parent / 'users').resolve()
                        row.update(active_version='', chunk_count=0, progress=0, status='failed', error_msg='原文件不存在，请重新上传')
                        if original.is_relative_to(source_root) and original.is_file():
                            content = original.read_bytes()
                            key = f"{row['user_id']}/originals/{row['id']}/{Path(row['filename']).name}"
                            row['file_path'] = store.put(key, content)
                            row.update(status='queued', error_msg='')
                            job = dict(user_id=row['user_id'], doc_id=row['id'], content_hash=hashlib.sha256(content).hexdigest())
                    await conn.execute(table.insert().values(**row))
                    if job:
                        await conn.execute(IngestionJob.__table__.insert().values(**job))
        print('应用数据迁移完成；文档由 Worker 重建索引。源数据库未修改。')
    finally:
        source.close()
        await engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    asyncio.run(migrate(args.sqlite, args.apply))
