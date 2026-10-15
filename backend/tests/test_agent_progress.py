import json
from app.agents.progress import public_arguments, public_result


def test_progress_projects_only_business_details():
    args = {'source_id': 'sales', 'sql': 'SELECT total FROM dataset', 'api_key': 'private'}
    assert public_arguments('execute_readonly_sql', json.dumps(args)) == {
        'source_id': 'sales', 'sql': 'SELECT total FROM dataset'}
    assert public_arguments('UnknownAnswer', json.dumps(args)) == {}
    assert public_arguments('execute_readonly_sql', '{partial') == {}
    result = public_result(json.dumps({'citation_id': 'Q1', 'rows': list(range(20)), 'api_key': 'private'}), [
        {'citation_id': 'Q1', 'rows': list(range(50)), 'sql': 'SELECT total FROM dataset LIMIT 500', 'source_name': '销售'}])
    assert result['row_count'] == 50
    assert result['source_name'] == '销售'
    assert result['sql'].endswith('LIMIT 500')
    assert 'rows' not in result and 'api_key' not in result


def test_progress_keeps_failures_and_empty_queries():
    assert public_result('{"error":"查询条件无效"}') == {'status': 'failed', 'error': '查询条件无效'}
    assert public_result('{"rows":[],"truncated":true}') == {'status': 'completed', 'row_count': 0, 'truncated': True}
