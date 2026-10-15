"""Explicit chart requests also apply to reused, authorized query evidence."""
import pytest

from app.agents.answer import FinalAnswer, AnswerSection
from app.agents.executor import AgentExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,disabled,truncated,count,expected', [
    ('bar', False, False, 2, 'bar'),
    ('line', False, False, 2, 'line'),
    (None, False, False, 2, None),
    ('bar', True, False, 2, None),
    ('bar', False, True, 2, None),
    ('bar', False, False, 1, None),
])
async def test_final_answer_applies_current_chart_request_to_history(
    monkeypatch, kind, disabled, truncated, count, expected,
):
    archived = {'query_id': 'historical', 'citation_id': 'Qhistorical',
                'source_name': '销售', 'truncated': truncated, 'chart': None,
                'rows': [{'region': '华北', 'revenue': 556427.5},
                         {'region': '西北', 'revenue': 447806.7}][:count]}
    async def query_result(*args):
        return archived
    monkeypatch.setattr('app.agents.evidence.query_result', query_result)
    executor = AgentExecutor('user', [], {}, enable_suggestions=False)
    executor.sql.conversation_id, executor.sql.scope_version = 'conversation', 1
    executor.sql.chart_type, executor.sql.charts_disabled = kind, disabled
    answer = FinalAnswer(sections=[AnswerSection(title='收入', summary='收入已汇总。',
                         query_id='Qhistorical', show_table=True)], suggestions=[])
    await executor.validate_answer(answer)
    chart = executor.sql.queries[0]['chart']
    assert (chart['type'] if chart else None) == expected
    if chart:
        assert chart['data'] == archived['rows']


@pytest.mark.asyncio
async def test_explicit_request_only_charts_referenced_results():
    executor = AgentExecutor('user', [], {}, enable_suggestions=False)
    executor.sql.chart_type = 'bar'
    executor.sql.queries = [{'citation_id': 'Qexploration', 'source_name': '销售',
                         'rows': [{'region': '甲', 'amount': 1}, {'region': '乙', 'amount': 2}],
                         'chart': None}]
    answer = FinalAnswer(sections=[AnswerSection(title='说明', summary='需要确认统计口径。')], suggestions=[])
    await executor.validate_answer(answer)
    assert executor.sql.queries[0]['chart'] is None
