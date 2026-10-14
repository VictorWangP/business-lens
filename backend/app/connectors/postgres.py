from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from app.config import settings
from app.infrastructure.credentials import decrypt
from app.analytics.sql_policy import validate_sql


def connection_url(secret: str) -> str:
    try:
        url = make_url(decrypt(secret))
    except ArgumentError as exc:
        raise ValueError('业务数据库连接地址无效') from exc
    if not url.host or not url.database or not url.username:
        raise ValueError('连接地址必须包含主机、数据库和只读用户名')
    if url.drivername not in {'postgresql', 'postgresql+asyncpg'}:
        raise ValueError('首期仅支持 PostgreSQL 数据源')
    return url.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False)


@asynccontextmanager
async def business_connection(source):
    engine = create_async_engine(connection_url(source.connection_secret), pool_size=1, max_overflow=0,
                                 connect_args={'timeout': 10, 'command_timeout': settings.SQL_TIMEOUT_MS / 1000})
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text('SET TRANSACTION READ ONLY'))
                await conn.execute(text("SELECT set_config('statement_timeout', :v, true)"), {'v': str(settings.SQL_TIMEOUT_MS)})
                await conn.execute(text("SELECT set_config('search_path', 'pg_catalog', true)"))
                role = (await conn.execute(text('SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=current_user'))).one()
                if any(role):
                    raise ValueError('业务连接必须使用无超级用户、无绕过 RLS、无创建角色/数据库权限的只读账号')
                unsafe = await conn.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.table_privileges WHERE grantee=current_user AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE'))"))
                if unsafe:
                    raise ValueError('业务账号具有写入权限，请配置专用只读账号')
                for view in source.allowed_views:
                    owner = await conn.scalar(text("""SELECT pg_get_userbyid(c.relowner)=current_user
                        FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid
                        WHERE n.nspname=:schema AND c.relname=:view AND c.relkind='v' """),
                        {'schema': source.schema_name, 'view': view})
                    if owner is None or owner:
                        raise ValueError('只允许读取非当前账号拥有的授权视图')
                yield conn
    finally:
        await engine.dispose()


async def inspect_source(source) -> list[dict]:
    async with business_connection(source) as conn:
        rows = (await conn.execute(text('''
            SELECT c.table_name, c.column_name, c.data_type
            FROM information_schema.columns c
            JOIN information_schema.views v ON v.table_schema=c.table_schema AND v.table_name=c.table_name
            WHERE c.table_schema=:schema
            ORDER BY c.table_name, c.ordinal_position
        '''), {'schema': source.schema_name})).mappings().all()
        result = [dict(r) for r in rows if r['table_name'] in source.allowed_views]
        found = {r['table_name'] for r in result}
        if found != set(source.allowed_views):
            raise ValueError('部分授权视图不存在或当前业务账号无法访问')
        return result


async def execute(source, sql: str, params: dict | None = None) -> dict:
    approved = validate_sql(sql, source.schema_name, source.allowed_views)
    async with business_connection(source) as conn:
        rows = (await conn.execute(text(approved), params or {})).mappings().all()
        return {'rows': [dict(r) for r in rows[:settings.SQL_MAX_ROWS]],
                'truncated': len(rows) > settings.SQL_MAX_ROWS, 'sql': approved}
