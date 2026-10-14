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

@pytest.mark.asyncio
async def test_pgvector_chinese_fusion_retriever(monkeypatch):
    import psycopg
    from psycopg import sql
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.database import Base
    from app.models.user import User
    from app.models.knowledge import KnowledgeBase, Document
    from app.models.platform import DocumentChunk
    from app.infrastructure.embeddings import EmbeddingProvider
    from app.retrieval.retriever import KnowledgeRetriever
    schema = 'vector_test_' + uuid.uuid4().hex[:12]
    admin_url = make_url(os.environ['RAG_TEST_POSTGRES_URL']).set(drivername='postgresql')
    async with await psycopg.AsyncConnection.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as admin:
        await admin.execute('CREATE EXTENSION IF NOT EXISTS vector')
        await admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        engine = create_async_engine(admin_url.set(drivername='postgresql+asyncpg'), connect_args={'server_settings':{'search_path':schema+',public'}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            provider = EmbeddingProvider({'base_url':'http://test','model_id':'test','api_key':'test'})
            async with sessions() as db:
                user=User(username='vector-user', hashed_password='unused'); db.add(user); await db.flush()
                kb=KnowledgeBase(user_id=user.id,name='政策'); db.add(kb); await db.flush()
                doc=Document(user_id=user.id,kb_id=kb.id,filename='policy.md',file_path='unused',active_version='v1'); db.add(doc); await db.flush()
                db.add(DocumentChunk(id='chunk1',user_id=user.id,kb_id=kb.id,doc_id=doc.id,version='v1',chunk_index=0,
                    content='华东折扣政策',meta={'filename':'policy.md'},embedding_profile=provider.profile,embedding=[1.,0.,0.],keywords='华东 折扣 政策'))
                await db.commit(); uid, kid=user.id,kb.id
            async def for_user(cls, db, uid): return provider
            async def embed(self,texts): return [[1.,0.,0.] for _ in texts]
            monkeypatch.setattr(EmbeddingProvider,'for_user',classmethod(for_user))
            monkeypatch.setattr(EmbeddingProvider,'embed',embed)
            monkeypatch.setattr('app.retrieval.retriever.AsyncSessionLocal',sessions)
            result=await KnowledgeRetriever(uid,[kid]).aretrieve('华东折扣')
            assert result[0].node.node_id=='chunk1'
            assert await KnowledgeRetriever('other',[kid]).aretrieve('华东折扣') == []
        finally:
            await engine.dispose()
            await admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
