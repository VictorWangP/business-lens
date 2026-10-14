"""Parse a single read-only query and resolve every relation against approved views."""
import re
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.dialects.postgres import Postgres
from sqlglot.dialects.duckdb import DuckDB
from sqlglot.dialects.sqlite import SQLite
from app.config import settings

SAFE_FUNCTIONS = {
    'SUM', 'AVG', 'MIN', 'MAX', 'COUNT', 'COALESCE', 'NULLIF', 'ROUND', 'ABS',
    'LOWER', 'UPPER', 'LENGTH', 'TRIM', 'SUBSTRING', 'DATE_TRUNC', 'EXTRACT',
    'CURRENT_DATE', 'CURRENT_TIMESTAMP', 'CAST', 'CASE', 'IF', 'ROW_NUMBER',
    'AND', 'OR', 'TIMESTAMP_TRUNC', 'RANK', 'DENSE_RANK', 'LAG', 'LEAD', 'FIRST_VALUE', 'LAST_VALUE',
    'GREATEST', 'LEAST', 'CONCAT', 'TO_CHAR', 'POWER', 'FLOOR', 'CEIL',
    'PERCENTILE_CONT', 'PERCENTILE_DISC', 'WITHIN_GROUP', 'ANONYMOUS',
}
SAFE_FUNCTIONS.remove('ANONYMOUS')
class SQLAlchemyPostgres(Postgres):
    class Generator(Postgres.Generator):
        def placeholder_sql(self, expression):
            if not expression.name or expression.name not in {'start_date', 'end_date'}:
                raise ValueError('仅支持 start_date 与 end_date 日期参数')
            return ':' + expression.name

class BoundedDuckDB(DuckDB):
    class Generator(DuckDB.Generator):
        def placeholder_sql(self, expression):
            return '$' + checked_parameter(expression)

class BoundedSQLite(SQLite):
    class Generator(SQLite.Generator):
        def placeholder_sql(self, expression):
            return ':' + checked_parameter(expression)

def checked_parameter(expression):
    if expression.name not in {'start_date', 'end_date'}:
        raise ValueError('仅支持 start_date 与 end_date 日期参数')
    return expression.name

IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def validate_sql(sql: str, schema: str, views: list[str], dialect: str = 'postgres') -> str:
    if len(sql) > 20000 or not IDENTIFIER.fullmatch(schema):
        raise ValueError('SQL 过长或 schema 无效')
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValueError('SQL 语法无效') from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ValueError('仅允许单条 SELECT 查询')
    tree = statements[0]
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Command, exp.Into, exp.Lock, exp.Set)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise ValueError('查询包含禁止的写入或锁定操作')
    for fn in tree.find_all(exp.Func):
        name = fn.name.upper() if isinstance(fn, exp.Anonymous) else fn.sql_name().upper()
        if name not in SAFE_FUNCTIONS or isinstance(fn.parent, exp.Dot):
            raise ValueError(f'不允许的函数: {name}')
    for cast in tree.find_all(exp.Cast):
        dtype = cast.args['to'].this
        if not hasattr(dtype, 'value') or dtype.value not in {
            'TEXT', 'VARCHAR', 'INT', 'BIGINT', 'SMALLINT', 'DATE', 'TIMESTAMP',
            'TIMESTAMPTZ', 'DOUBLE', 'FLOAT', 'BOOLEAN', 'DECIMAL',
        }:
            raise ValueError('不允许的类型转换')
    if any(isinstance(n, (exp.Parameter, exp.SessionParameter)) for n in tree.walk()):
        raise ValueError('不支持的 SQL 参数')
    relations = 0
    for scope in traverse_scope(tree):
        for _, (_, source) in scope.selected_sources.items():
            if isinstance(source, exp.Table):
                if source.catalog or (source.db and source.db != schema) or source.name not in views:
                    raise ValueError(f'未授权的数据集: {source.name}')
                source.set('db', exp.to_identifier(schema, quoted=True))
                source.set('this', exp.to_identifier(source.name, quoted=True))
                relations += 1
    if not relations:
        raise ValueError('查询必须读取授权业务视图')
    # A wrapper enforces an upper bound even when an inner query specifies its own LIMIT.
    return f'SELECT * FROM ({tree.sql(dialect={'postgres':SQLAlchemyPostgres, 'duckdb':BoundedDuckDB, 'sqlite':BoundedSQLite}[dialect])}) AS business_result LIMIT {settings.SQL_MAX_ROWS + 1}'
