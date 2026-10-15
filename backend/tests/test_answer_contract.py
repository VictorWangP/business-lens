import json
import pytest
from app.agents.answer import parse_answer, render_answer, AnswerValidationError

QUERY = {'citation_id':'Q1','rows':[{'月份':'十月','收入':10}], 'truncated':False}

def parse(section=None, suggestions=None, **extra):
    payload={'version':1,'sections':[section or {'title':'趋势','summary':'收入为 10 [查询 Q1]'}],
             'suggestions':suggestions if suggestions is not None else []}
    payload.update(extra)
    return parse_answer(json.dumps(payload,ensure_ascii=False),enabled=False,allow_code=False,queries=[QUERY])


@pytest.mark.parametrize('source',[
    '```mermaid\nxychart-beta\nline [1,2]\n```',
    '~~~python\nimport matplotlib.pyplot as plt\n~~~',
    '```json\n{"chart":{"data":[1,2]}}\n```',
    '    xychart-beta\n    line [1,2]',
    '# 偷渡标题', '<script>alert(1)</script>',
    '| 月份 | 收入 |\n| --- | --- |\n| 十月 | 10 |',
])
def test_summary_rejects_implementation_blocks_by_ast_type(source):
    with pytest.raises(AnswerValidationError):parse({'title':'趋势','summary':source})


@pytest.mark.parametrize('section',[
    {'title':'趋势','summary':'事实 [查询 Q9]'},
    {'title':'趋势','summary':'事实 [来源 S9]'},
    {'title':'趋势','summary':'事实','query_id':'Q9'},
    {'title':'趋势','summary':'事实','show_table':True},
    {'title':'趋势','summary':'事实','code':{'language':'python','content':'print(1)'}},
])
def test_unauthorized_references_and_code_are_rejected(section):
    with pytest.raises(AnswerValidationError):parse(section)


def test_unknown_chart_fields_are_rejected():
    with pytest.raises(AnswerValidationError):parse(chart={'data':[1,2]})


def test_numbered_prose_does_not_duplicate_exact_table_data():
    answer=parse({'title':'7. 收入','summary':'数据如下。','query_id':'Q1','show_table':True})
    assert render_answer(answer)=='## 1. 收入\n\n数据如下。'
    assert answer.sections[0].show_table and answer.sections[0].query_id=='Q1'


def test_only_explicit_code_field_is_allowed_when_requested():
    payload={'sections':[{'title':'示例','summary':'按需求提供示例。','code':{'language':'python','content':'print(1)'}}], 'suggestions':[]}
    answer=parse_answer(json.dumps(payload),enabled=False,allow_code=True,queries=[])
    assert '```python\nprint(1)\n```' in render_answer(answer)


@pytest.mark.parametrize('suggestions',[[],['a'],['a','a','b'],['a','b',' ']])
def test_enabled_feature_requires_exactly_three_distinct_questions(suggestions):
    with pytest.raises(AnswerValidationError):
        parse_answer(json.dumps({'sections':[{'title':'结果','summary':'结果。'}],'suggestions':suggestions}),
                     enabled=True,allow_code=False,queries=[])


def test_parse_answer_maps_uuid_query_id_to_citation_id():
    query_with_uuid = {'query_id': '6c483c05-e183-4f4f-95cf-eb3f9a7ce4c5', 'citation_id': 'Q6c483c05e1834f4f95cfeb3f9a7ce4c5', 'rows': [{'a': 1}], 'truncated': False}
    payload = {
        'version': 1,
        'sections': [{
            'title': '商机分析',
            'summary': '阶段统计如 [查询 6c483c05-e183-4f4f-95cf-eb3f9a7ce4c5]',
            'query_id': '6c483c05-e183-4f4f-95cf-eb3f9a7ce4c5',
            'show_table': True
        }],
        'suggestions': []
    }
    answer = parse_answer(json.dumps(payload, ensure_ascii=False), enabled=False, allow_code=False, queries=[query_with_uuid])
    assert answer.sections[0].query_id == 'Q6c483c05e1834f4f95cfeb3f9a7ce4c5'
    assert '[查询 Q6c483c05e1834f4f95cfeb3f9a7ce4c5]' in answer.sections[0].summary

