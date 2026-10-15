"""Public execution details, separate from model reasoning and raw tool evidence."""
import json

ARGUMENT_FIELDS = {
    'list_available_resources': (),
    'get_business_schema': ('source_id',),
    'execute_readonly_sql': ('source_id', 'sql'),
    'query_metrics': ('metric_id', 'start_date', 'end_date'),
    'read_query_result': ('query_id', 'offset', 'limit'),
    'read_tool_result': ('tool_result_id', 'offset'),
    'ask_clarification': ('question',),
}


def public_arguments(name, text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in ARGUMENT_FIELDS.get(name, ())
            if key in data and isinstance(data[key], (str, int, float))}


def public_result(text, queries=()):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {'status': 'completed'}
    if not isinstance(data, dict):
        return {'status': 'completed'}
    query = next((q for q in queries if q.get('citation_id') and q['citation_id'] == data.get('citation_id')), None)
    if query is not None:
        data = {**data, **query}
    result = {'status': 'failed' if data.get('error') else 'completed'}
    for key in ('source_id', 'source_name', 'sql', 'metric', 'definition', 'error', 'truncated', 'citation_id'):
        if key in data and isinstance(data[key], (str, bool)):
            result[key] = data[key]
    if isinstance(data.get('rows'), list):
        result['row_count'] = len(data['rows'])
    if isinstance(data.get('sources'), list):
        result['sources'] = [{'id': s['id'], 'name': s['name']} for s in data['sources']
                             if isinstance(s, dict) and isinstance(s.get('id'), str) and isinstance(s.get('name'), str)]
    return result
