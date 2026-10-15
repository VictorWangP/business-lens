"""Opt-in: isolated schema + temporary reader role in a dedicated PostgreSQL test database.
RAG_TEST_POSTGRES_URL must identify an administrator on that test database.
"""
import os
import uuid
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy.engine import make_url
from app.infrastructure.credentials import encrypt
from app.connectors.postgres import execute, inspect_source

pytestmark = pytest.mark.skipif(not os.environ.get('RAG_TEST_POSTGRES_URL'), reason='未配置独立 PostgreSQL 集成测试库')

@pytest.mark.asyncio
async def test_real_postgres_readonly_views_and_decimal():
    import psycopg
    from psycopg import sql
    admin_url = make_url(os.environ['RAG_TEST_POSTGRES_URL']).set(drivername='postgresql')
    suffix = uuid.uuid4().hex[:16]
    schema, reader, password = 'test_' + suffix, 'reader_' + suffix, uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as admin:
        await admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            await admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(reader), sql.Literal(password)))
            await admin.execute(sql.SQL('CREATE TABLE {}.orders (amount NUMERIC(18,2), order_date DATE, region TEXT)').format(sql.Identifier(schema)))
            await admin.execute(sql.SQL("INSERT INTO {}.orders VALUES (0.10, '2026-01-01', '华东'), (0.20, '2026-01-02', '华东')").format(sql.Identifier(schema)))
            await admin.execute(sql.SQL('CREATE VIEW {}.sales AS SELECT * FROM {}.orders').format(sql.Identifier(schema),sql.Identifier(schema)))
            await admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(reader)))
            await admin.execute(sql.SQL('GRANT SELECT ON {}.sales TO {}').format(sql.Identifier(schema),sql.Identifier(reader)))
            url = admin_url.set(username=reader, password=password)
            source = SimpleNamespace(connection_secret=encrypt(url.render_as_string(hide_password=False)), schema_name=schema, allowed_views=['sales'])
            assert len(await inspect_source(source)) == 3
            result = await execute(source, 'SELECT SUM(amount) AS total FROM sales WHERE order_date >= :start_date AND order_date < :end_date',
                                   {'start_date': __import__('datetime').date(2026,1,1), 'end_date': __import__('datetime').date(2026,2,1)})
            assert result['rows'] == [{'total':Decimal('0.30')}]
            assert result['truncated'] is False
            with pytest.raises(ValueError):
                await execute(source, 'SELECT * FROM orders')
            with pytest.raises(ValueError):
                await execute(source, 'DELETE FROM sales')
        finally:
            await admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            await admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(reader)))
