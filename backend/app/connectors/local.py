"""Private, immutable file datasets. Queries cannot access the host filesystem."""
import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from app.config import settings
from app.infrastructure.credentials import decrypt
from app.analytics.sql_policy import validate_sql, IDENTIFIER


def dataset_path(source) -> Path:
    value = decrypt(source.connection_secret)
    prefix = source.kind + '://'
    if source.kind not in {'duckdb', 'sqlite'} or not value.startswith(prefix):
        raise ValueError('文件数据源地址无效')
    path = Path(value[len(prefix):]).resolve()
    root = (settings.USER_STORAGE_DIR / source.user_id / 'data_sources').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('数据集不存在或无权访问')
    return path


def _read(source, sql, params=None):
    path = dataset_path(source)
    if source.kind == 'duckdb':
        import duckdb
        conn = duckdb.connect(str(path), read_only=True, config={
            'enable_external_access': 'false', 'autoinstall_known_extensions': 'false',
            'autoload_known_extensions': 'false', 'threads': '2', 'memory_limit': '256MB',
        })
        timer = threading.Timer(settings.SQL_TIMEOUT_MS / 1000, conn.interrupt)
        try:
            timer.start()
            result = conn.execute(sql, params or {})
            columns = [c[0] for c in result.description]
            rows = result.fetchmany(settings.SQL_MAX_ROWS + 1)
        finally:
            timer.cancel()
            timer.join()
            conn.close()
    else:
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        deadline = time.monotonic() + settings.SQL_TIMEOUT_MS / 1000
        try:
            conn.execute('PRAGMA query_only=ON')
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            result = conn.execute(sql, params or {})
            columns = [c[0] for c in result.description]
            rows = result.fetchmany(settings.SQL_MAX_ROWS + 1)
        finally:
            conn.close()
    if len(set(columns)) != len(columns):
        raise ValueError('查询结果存在重复列名，请给列设置不同别名')
    return {'rows': [dict(zip(columns, row)) for row in rows[:settings.SQL_MAX_ROWS]],
            'truncated': len(rows) > settings.SQL_MAX_ROWS, 'sql': sql}


async def execute(source, sql: str, params=None):
    approved = validate_sql(sql, source.schema_name, source.allowed_views, dialect=source.kind)
    return await asyncio.to_thread(_read, source, approved, params)


async def inspect_source(source):
    def inspect():
        path = dataset_path(source)
        if source.kind == 'duckdb':
            import duckdb
            with duckdb.connect(str(path), read_only=True, config={'enable_external_access':'false',
                    'autoinstall_known_extensions':'false', 'autoload_known_extensions':'false',
                    'threads':'2', 'memory_limit':'256MB'}) as conn:
                rows = conn.execute('SELECT table_name,column_name,data_type FROM information_schema.columns '
                    'WHERE table_schema=? ORDER BY table_name,ordinal_position', [source.schema_name]).fetchall()
            result = [dict(zip(['table_name','column_name','data_type'], r)) for r in rows if r[0] in source.allowed_views]
        else:
            with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
                result = []
                for table in source.allowed_views:
                    if not IDENTIFIER.fullmatch(table):
                        raise ValueError('数据集名称无效')
                    result.extend({'table_name':table,'column_name':r[1],'data_type':r[2]}
                                  for r in conn.execute(f'PRAGMA table_info("{table}")'))
        if {r['table_name'] for r in result} != set(source.allowed_views):
            raise ValueError('部分授权数据集不存在')
        return result
    return await asyncio.to_thread(inspect)
