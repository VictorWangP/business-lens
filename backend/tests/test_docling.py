from pathlib import Path
from app.ingestion.parser import parse_document

def test_docling_markdown_preserves_heading_and_table(tmp_path):
    path = tmp_path / 'policy.md'
    path.write_text('# 华东折扣政策\n\n主管审批后生效。\n\n| 客户 | 折扣 |\n| --- | --- |\n| 华东 | 5% |\n', encoding='utf-8')
    nodes, structure, markdown = parse_document(path, 'version')
    assert nodes and structure and '华东' in markdown
    assert all(n.metadata['parser'] == 'docling' for n in nodes)
    assert any('华东折扣政策' in n.metadata['headings'] for n in nodes)
    assert any('5%' in n.text for n in nodes)
    assert all(n.metadata['element_refs'] for n in nodes)
