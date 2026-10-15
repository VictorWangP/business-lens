"""SQL tools and their per-run evidence; independent of graph orchestration."""
import asyncio
import json
import logging
from datetime import date, datetime, timezone
from functools import wraps
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphInterrupt
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.platform import DataSource, MetricDefinition
from app.connectors.registry import inspect_source, execute
from app.analytics.presentation import json_value, chart_from_rows, metrics_from_rows
from app.agents.context import bounded_result, result_page, serialized_tokens
from app.infrastructure.telemetry import tracer

logger = logging.getLogger(__name__)


class SQLTools:
    def __init__(self, user_id: str, source_ids: list[str]):
        self.user_id, self.source_ids = user_id, source_ids
        self.conversation_id, self.scope_version = '', 0
        self.pending = asyncio.Queue()
        self.calls, self.errors = 0, 0
        self.queries = []
        self.tool_results = {}
        self.chart_type = None
        self.charts_disabled = False

    def tool(self, fn):
        @wraps(fn)
        async def invoke(**kwargs):
            self.calls += 1
            try:
                with tracer.start_as_current_span('tool.' + fn.__name__):
                    result = json_value(await fn(**kwargs))
                # Artifact carries complete exact evidence; model context gets a bounded view.
                evidence = dict(result) if isinstance(result, dict) else result
                if isinstance(evidence, dict):
                    for key in ('chart', 'metrics', 'sql', 'parameters'):
                        evidence.pop(key, None)
                if isinstance(evidence, dict) and 'rows' in evidence:
                    evidence['rows'] = evidence['rows'][:20]
                    evidence['model_rows_truncated'] = bool(result.get('model_rows_truncated')) or len(result['rows']) > 20
                if (serialized_tokens(evidence) > settings.AGENT_TOOL_OUTPUT_TOKENS
                        or fn.__name__ in {'list_available_resources', 'get_business_schema'}):
                    import uuid
                    result_id = 'T' + uuid.uuid4().hex
                    self.tool_results[result_id] = result
                    await self.pending.put({'type': 'tool_result', 'tool_result_id': result_id, 'tool_name': fn.__name__, 'result': result})
                    evidence = bounded_result(evidence, result_id, settings.AGENT_TOOL_OUTPUT_TOKENS)
                    if isinstance(evidence, dict) and not evidence.get('tool_result_id'):
                        evidence = bounded_result({**evidence, 'tool_result_id': result_id}, result_id, settings.AGENT_TOOL_OUTPUT_TOKENS)
                    result = {**result, 'tool_result_id': result_id} if isinstance(result, dict) else {'value': result, 'tool_result_id': result_id}
                    logger.info('agent_tool_output run=%s tool=%s result_id=%s preview_tokens=%d limit=%d',
                                getattr(self, 'run_id', ''), fn.__name__, result_id, serialized_tokens(evidence), settings.AGENT_TOOL_OUTPUT_TOKENS)
                return json.dumps(evidence, ensure_ascii=False), result
            except GraphInterrupt:
                raise
            except Exception as exc:
                self.errors += 1
                message = str(exc) if isinstance(exc, ValueError) else '工具执行失败，请检查数据源、模型配置或查询限制'
                error = {'error': message, 'category': type(exc).__name__}
                if serialized_tokens(error) > settings.AGENT_TOOL_OUTPUT_TOKENS:
                    import uuid
                    result_id = 'T' + uuid.uuid4().hex
                    self.tool_results[result_id] = error
                    await self.pending.put({'type': 'tool_result', 'tool_result_id': result_id, 'tool_name': fn.__name__, 'result': error})
                    preview = bounded_result(error, result_id, settings.AGENT_TOOL_OUTPUT_TOKENS)
                    return json.dumps(preview, ensure_ascii=False), {**error, 'tool_result_id': result_id}
                return json.dumps(error, ensure_ascii=False), error
        return StructuredTool.from_function(coroutine=invoke, response_format='content_and_artifact')

    async def source(self, source_id):
        if source_id not in self.source_ids:
            raise ValueError('该数据源未被选中')
        async with AsyncSessionLocal() as db:
            source = await db.scalar(select(DataSource).where(DataSource.id == source_id, DataSource.user_id == self.user_id))
            if not source:
                raise ValueError('数据源不存在或未授权')
            return source

    def tools(self):
        async def list_available_resources() -> dict:
            """列出本次允许访问的业务数据源和指标定义。"""
            async with AsyncSessionLocal() as db:
                sources = (await db.scalars(select(DataSource).where(DataSource.user_id == self.user_id, DataSource.id.in_(self.source_ids)))).all()
                metrics = (await db.scalars(select(MetricDefinition).where(MetricDefinition.user_id == self.user_id, MetricDefinition.source_id.in_(self.source_ids)))).all()
                return {'sources': [{'id': s.id, 'name': s.name, 'kind': s.kind, 'description': s.description} for s in sources],
                        'metrics': [{'id': m.id, 'name': m.name, 'description': m.description, 'unit': m.unit} for m in metrics]}

        async def get_business_schema(source_id: str) -> dict:
            """读取数据源的实际授权视图、列及类型。生成 SQL 前必须调用。"""
            source = await self.source(source_id)
            return {'source_id': source.id, 'source_name': source.name, 'schema': source.schema_name, 'dialect': source.kind, 'columns': await inspect_source(source)}

        async def execute_readonly_sql(source_id: str, sql: str, chart_type: str = 'none') -> dict:
            """执行只读 SQL。chart_type 默认 none；仅适合趋势/对比/占比或明确绘图需求时选 line/bar/pie，明细、名单及中间查询不绘图。"""
            source = await self.source(source_id)
            return await self.query(source, sql, chart_type=chart_type)

        async def query_metrics(metric_id: str, start_date: str, end_date: str, chart_type: str = 'none') -> dict:
            """查询指标。日期 YYYY-MM-DD，开始包含、结束不包含。chart_type 默认 none，仅适合可视化时选 line/bar/pie。"""
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
            if end <= start:
                raise ValueError('结束日期必须大于开始日期')
            async with AsyncSessionLocal() as db:
                metric = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == metric_id,
                    MetricDefinition.user_id == self.user_id, MetricDefinition.source_id.in_(self.source_ids)))
                if not metric:
                    raise ValueError('指标不存在或未授权')
            source = await self.source(metric.source_id)
            result = await self.query(source, metric.sql_template, {'start_date': start, 'end_date': end}, metric.unit, chart_type)
            return {**result, 'metric': metric.name, 'definition': metric.description, 'unit': metric.unit}

        async def read_query_result(query_id: str, offset: int = 0, limit: int = 20) -> dict:
            """按页读取历史查询的精确结果。使用 citation_id；不能从聊天摘要重建数字。"""
            if offset < 0 or not 1 <= limit <= 20:
                raise ValueError('offset 必须非负，limit 必须在 1 到 20 之间')
            result = next((q for q in self.queries if q.get('query_id') == query_id or q.get('citation_id') == query_id), None)
            if result is None:
                from app.agents.evidence import query_result
                result = await query_result(self.user_id, self.conversation_id, self.scope_version, query_id)
                if not any(query['query_id'] == result['query_id'] for query in self.queries):
                    self.queries.append(result)
            end = offset + limit
            return {**result, 'rows': result['rows'][offset:end], 'total_rows': len(result['rows']),
                    'next_offset': end if end < len(result['rows']) else None,
                    'model_rows_truncated': offset > 0 or end < len(result['rows'])}

        async def read_tool_result(tool_result_id: str, offset: int = 0) -> dict:
            """分段读取已保存的大工具结果；offset 使用上一页 next_offset，内容为 JSON 文本片段。"""
            from app.agents.evidence import tool_result
            result = self.tool_results.get(tool_result_id)
            if result is None:
                result = await tool_result(self.user_id, self.conversation_id, self.scope_version, tool_result_id)
            if isinstance(result, dict) and result.get('source_id'):
                await self.source(result['source_id'])
            return result_page(result, tool_result_id, offset, settings.AGENT_TOOL_OUTPUT_TOKENS)

        async def ask_clarification(question: str) -> dict:
            """关键业务条件缺失且无法可靠判断时暂停，向用户询问一个具体问题后继续。"""
            from langgraph.types import interrupt
            response = interrupt({'reason': 'input_required', 'message': question,
                'responseSchema': {'type': 'string', 'minLength': 1, 'maxLength': 2000}})
            return {'clarification': response}

        return [self.tool(fn) for fn in (list_available_resources,
                                         get_business_schema, execute_readonly_sql, query_metrics, read_query_result, read_tool_result, ask_clarification)]

    async def query(self, source, sql, params=None, unit='', chart_type='none'):
        import uuid
        result = await execute(source, sql, params)
        query_id = str(uuid.uuid4())
        kind = self.chart_type or chart_type
        chart = None
        if not self.charts_disabled and not result['truncated'] and kind in {'bar', 'line', 'pie'} and len(result['rows']) >= 2:
            chart = chart_from_rows(result['rows'], source.name, kind)
        metrics = [] if result['truncated'] else metrics_from_rows(result['rows'], unit)
        result = {**json_value(result), 'query_id': query_id, 'citation_id': 'Q' + query_id.replace('-', ''), 'source_id': source.id,
                  'source_name': source.name, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'parameters': json_value(params or {}), 'chart': chart, 'metrics': metrics}
        self.queries.append(result)
        await self.pending.put({'type': 'query_result', **result})
        return {**result, 'presentation': {'chart_ready': bool(chart), 'chart_type': chart['type'] if chart else None,
            'query_id': result['citation_id'], 'series': chart['y_keys'] if chart else [],
            'y_axes': 1 if chart else 0, 'note': '图表由应用组件展示，不要在正文生成绘图代码或配置'}}

