import logging
import asyncio
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.platform import DataSource, MetricDefinition
from app.security.auth import get_current_user
from app.infrastructure.credentials import encrypt
from app.analytics.sql_policy import IDENTIFIER, validate_sql
from app.connectors.registry import inspect_source, execute, dialect
from app.connectors.postgres import connection_url
from app.application.tabular import import_file
from app.config import settings
from app.analytics.presentation import json_value

router = APIRouter(prefix='/data-sources', tags=['真实业务数据源'])
logger = logging.getLogger(__name__)

class SourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    connection_url: str = Field(min_length=1, max_length=2048)
    schema_name: str = 'public'
    allowed_views: list[str] = Field(min_length=1, max_length=50)
    description: str = Field(default='', max_length=2000)

    @field_validator('schema_name')
    @classmethod
    def schema_valid(cls, v):
        if not IDENTIFIER.fullmatch(v) or v.startswith('pg_') or v == 'information_schema':
            raise ValueError('请使用业务 schema')
        return v

    @field_validator('allowed_views')
    @classmethod
    def views_valid(cls, v):
        if any(not IDENTIFIER.fullmatch(x) for x in v):
            raise ValueError('视图名称无效')
        return list(dict.fromkeys(v))

class QueryInput(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)

class MetricInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    sql_template: str = Field(min_length=1, max_length=20000)
    unit: str = Field(default='', max_length=30)

async def owned_source(db, user_id, source_id):
    source = await db.scalar(select(DataSource).where(DataSource.id == source_id, DataSource.user_id == user_id))
    if not source:
        raise HTTPException(404, '数据源不存在')
    return source

def public(source):
    return {'id': source.id, 'name': source.name, 'kind': source.kind, 'description': source.description,
            'schema_name': source.schema_name, 'allowed_views': source.allowed_views}

@router.get('')
async def list_sources(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sources = (await db.scalars(select(DataSource).where(DataSource.user_id == user.id))).all()
    return [public(s) for s in sources]

@router.post('/import')
async def import_source(file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=100),
                        sheet: str | None = Form(default=None, max_length=100),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    result = None
    try:
        # Validate the encryption key before writing any dataset files.
        encrypt('validation')
        result = await asyncio.to_thread(import_file, user.id, file.filename or '', content, sheet or None)
        source = DataSource(id=result['id'], user_id=user.id, name=name.strip(), kind='duckdb',
            connection_secret=encrypt('duckdb://' + str(result['path'])), schema_name='main',
            allowed_views=['dataset'], description=f"文件：{file.filename}；行数：{result['row_count']}" +
                (f"；工作表：{result['sheet']}" if result['sheet'] else ''))
        db.add(source)
        await db.commit()
        return {**public(source), 'row_count':result['row_count'], 'columns':result['columns'],
                'sheet':result['sheet'], 'sheets':result['sheets']}
    except ValueError as exc:
        if result: shutil.rmtree(result['path'].parent)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        if result: shutil.rmtree(result['path'].parent)
        logger.exception('File dataset import failed')
        raise HTTPException(422, '文件导入失败，请检查文件格式和服务存储空间')
    finally:
        await file.close()

@router.post('')
async def create_source(payload: SourceInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        secret = encrypt(payload.connection_url)
        connection_url(secret)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    source = DataSource(user_id=user.id, name=payload.name, kind='postgresql', connection_secret=secret,
                        schema_name=payload.schema_name, allowed_views=payload.allowed_views, description=payload.description)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return public(source)

@router.post('/{source_id}/test')
async def test_source(source_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    source = await owned_source(db, user.id, source_id)
    try:
        columns = await inspect_source(source)
        return {'status': 'ok', 'columns': columns}
    except Exception:
        logger.warning('Source connectivity failed: %s', source.id)
        raise HTTPException(422, '数据集不可读取，请检查文件、连接及授权范围')

@router.post('/{source_id}/query')
async def query_source(source_id: str, payload: QueryInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    source = await owned_source(db, user.id, source_id)
    try:
        return json_value(await execute(source, payload.sql))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        raise HTTPException(422, '业务查询失败，请检查 SQL、数据源及查询超时限制')

@router.get('/{source_id}/metrics')
async def list_metrics(source_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_source(db, user.id, source_id)
    return (await db.scalars(select(MetricDefinition).where(MetricDefinition.source_id == source_id, MetricDefinition.user_id == user.id))).all()

@router.post('/{source_id}/metrics')
async def create_metric(source_id: str, payload: MetricInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    source = await owned_source(db, user.id, source_id)
    try:
        validate_sql(payload.sql_template, source.schema_name, source.allowed_views, dialect=dialect(source))
        import sqlglot
        from sqlglot import exp
        placeholders = {p.name for p in sqlglot.parse_one(payload.sql_template, read=dialect(source)).find_all(exp.Placeholder)}
        if placeholders != {'start_date', 'end_date'}:
            raise ValueError('指标 SQL 必须使用 start_date 和 end_date 日期参数')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    metric = MetricDefinition(user_id=user.id, source_id=source.id, **payload.model_dump())
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return metric

@router.delete('/{source_id}', status_code=204)
async def delete_source(source_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await owned_source(db, user.id, source_id))
    await db.commit()

class SourceUpdateInput(SourceInput):
    connection_url: str | None = Field(default=None, max_length=2048)

@router.put('/{source_id}')
async def update_source(source_id: str, payload: SourceUpdateInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    source = await owned_source(db, user.id, source_id)
    if source.kind != 'postgresql':
        raise HTTPException(422, '文件数据集不可修改连接，请重新导入新文件')
    if payload.connection_url:
        try:
            secret = encrypt(payload.connection_url)
            connection_url(secret)
            source.connection_secret = secret
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    source.name, source.description = payload.name, payload.description
    source.schema_name, source.allowed_views = payload.schema_name, payload.allowed_views
    await db.commit()
    return public(source)

@router.delete('/{source_id}/metrics/{metric_id}', status_code=204)
async def delete_metric(source_id: str, metric_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_source(db, user.id, source_id)
    metric = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == metric_id,
                            MetricDefinition.source_id == source_id, MetricDefinition.user_id == user.id))
    if not metric:
        raise HTTPException(404, '指标不存在')
    await db.delete(metric)
    await db.commit()
