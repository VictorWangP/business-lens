"""After migrations, grant a non-owner runtime role only the required application DML."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from app.config import settings

async def provision():
    url = make_url(settings.DATABASE_URL).set(drivername='postgresql')
    async with await psycopg.AsyncConnection.connect(url.render_as_string(hide_password=False), autocommit=True) as conn:
        role = settings.APP_DATABASE_USER
        exists = await (await conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,))).fetchone()
        action = 'ALTER' if exists else 'CREATE'
        await conn.execute(sql.SQL(action + ' ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(
            sql.Identifier(role), sql.Literal(settings.APP_DATABASE_PASSWORD)))
        await conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(url.database), sql.Identifier(role)))
        await conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
        await conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        await conn.execute(sql.SQL('REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {}').format(sql.Identifier(role)))
        await conn.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
    print('运行账号权限已配置。')

if __name__ == '__main__':
    asyncio.run(provision())
