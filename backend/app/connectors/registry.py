"""Dispatch by source kind. Optional adapters are imported only when selected."""

def adapter(source):
    if source.kind in {'duckdb', 'sqlite'}:
        from app.connectors import local
        return local
    if source.kind == 'postgresql':
        from app.connectors import postgres
        return postgres
    raise ValueError('不支持的数据源类型')

async def inspect_source(source):
    return await adapter(source).inspect_source(source)

async def execute(source, sql, params=None):
    return await adapter(source).execute(source, sql, params)

def dialect(source):
    return 'postgres' if source.kind == 'postgresql' else source.kind
