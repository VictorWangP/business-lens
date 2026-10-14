"""One validated delivery contract; tool evidence never becomes answer source code."""
import json
import re
from typing import Literal

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

markdown = MarkdownIt('commonmark').enable('table')


class AnswerValidationError(ValueError):
    pass


class CodeExample(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    language: str = Field(default='', max_length=30, pattern=r'^[a-zA-Z0-9_+-]*$')
    content: str = Field(min_length=1, max_length=12000)


class AnswerSection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=6000)
    query_id: str | None = None
    show_table: bool = False
    code: CodeExample | None = None


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)
    version: Literal[1] = 1
    sections: list[AnswerSection] = Field(min_length=1, max_length=12)
    suggestions: list[str] = Field(max_length=3)


def requests_code(query: str) -> bool:
    return bool(re.search(r'代码|教程|绘图指南', query)) and not bool(
        re.search(r'(?:不要|无需|不用|不需要|不必|别).{0,12}(?:代码|教程|指南)', query))


def history_text(text: str, allow_code: bool = False) -> str:
    """Compatibility for saved free-form answers, by block type, not chart keywords."""
    if allow_code:
        return text
    lines = text.splitlines(keepends=True)
    ranges = [token.map for token in markdown.parse(text)
              if token.type in {'fence', 'code_block'} and token.map]
    for start, end in sorted(ranges, reverse=True):
        del lines[start:end]
    return ''.join(lines).strip()


def answer_prompt(enabled: bool) -> str:
    return (
        '\n最终回答必须只输出满足以下 JSON Schema 的 JSON 对象，不要代码围栏或 JSON 外的正文。'
        '\nsections 按业务问题组织，title 为不带数字的简洁标题；summary 只写业务结论、口径、限制和引用，'
        '可用 Markdown 强调和列表，不要标题、代码块、HTML、绘图教程或复制图表配置/数组。'
        '表格使用实际查询的 query_id（如 Q1）和 show_table=true，由应用按真实行集生成；否则 show_table=false。'
        '图表已通过独立通道准备，不在 JSON 中添加 chart、data 或绘图源码。'
        '只有用户明确索要代码/教程时才在 code 字段输出代码。'
        + ('suggestions 必须包含三个不同且具体相关的延伸问题。' if enabled else 'suggestions 必须为空数组，不生成延伸问题。')
        + '\nJSON Schema: ' + json.dumps(FinalAnswer.model_json_schema(), ensure_ascii=False)
    )


def parse_answer(raw: str, *, enabled: bool, allow_code: bool, queries: list[dict], citations: dict) -> FinalAnswer:
    try:
        # Tolerate a single JSON fence at the transport boundary; never display it.
        tokens = markdown.parse(raw)
        if len(tokens) == 1 and tokens[0].type == 'fence':
            raw = tokens[0].content
        answer = FinalAnswer.model_validate_json(raw)
        known_queries = {q['citation_id'] for q in queries}
        for section in answer.sections:
            section.title = re.sub(r'^\d+[.、．)]\s*', '', section.title.strip())
            title_tokens = markdown.parse(section.title)
            if not section.title or '\n' in section.title or '\r' in section.title or any(t.type != 'inline' and t.type not in {'paragraph_open', 'paragraph_close'} for t in title_tokens):
                raise ValueError('title 必须为单行文本')
            if not section.summary.strip():
                raise ValueError('summary 不能为空')
            if any(t.type in {'fence', 'code_block', 'html_block', 'heading_open', 'table_open'} or
                   any(c.type == 'html_inline' for c in (t.children or [])) for t in markdown.parse(section.summary)):
                raise ValueError('summary 不允许标题、代码、HTML 或表格；表格请引用查询')
            if section.query_id is not None and section.query_id not in known_queries:
                raise ValueError('query_id 必须引用实际查询')
            if section.show_table and not section.query_id:
                raise ValueError('show_table 需要 query_id')
            if section.code and not allow_code:
                raise ValueError('用户没有请求代码')
            for ref in re.findall(r'\[查询\s+([^\]]+)\]', section.summary):
                if ref.strip() not in known_queries:
                    raise ValueError('回答包含未执行的业务查询引用')
            for ref in re.findall(r'\[来源\s+([^\]]+)\]', section.summary):
                if ref.strip() not in citations:
                    raise ValueError('回答包含未检索到的来源引用')
        answer.suggestions = [item.strip() for item in answer.suggestions]
        expected = 3 if enabled else 0
        if len(answer.suggestions) != expected or any(not item or len(item) > 200 or '\n' in item or '`' in item for item in answer.suggestions) or len(set(answer.suggestions)) != expected:
            raise ValueError(f'suggestions 必须为 {expected} 个不同的非空问题')
        return answer
    except (ValueError, TypeError) as exc:
        # No provider body or draft text is leaked to logs/UI.
        reason = json.dumps([{'field': e['loc'], 'type': e['type']} for e in exc.errors()], ensure_ascii=False) if isinstance(exc, ValidationError) else str(exc)
        raise AnswerValidationError(reason) from exc


def render_answer(answer: FinalAnswer, queries: list[dict]) -> str:
    """Deterministic Markdown for the existing assistant-ui renderer/copy/TTS."""
    lookup = {q['citation_id']: q for q in queries}
    def cell(value):
        return str(value if value is not None else '').replace('\\', '\\\\').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;').replace('`', '\\`').replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
    parts = []
    for index, section in enumerate(answer.sections, 1):
        title = re.sub(r'^\d+[.、．)]\s*', '', section.title)
        parts.extend([f'## {index}. {cell(title)}', section.summary])
        if section.show_table:
            result = lookup[section.query_id]
            rows = result.get('rows', [])
            if rows:
                columns = list(rows[0])
                parts.append('\n'.join([
                    '| ' + ' | '.join(map(cell, columns)) + ' |',
                    '| ' + ' | '.join('---' for _ in columns) + ' |',
                    *['| ' + ' | '.join(cell(row.get(col)) for col in columns) + ' |' for row in rows],
                ]))
            else:
                parts.append('查询结果为空。')
            parts.append(f"[查询 {section.query_id}]" + (' 当前结果已截断，不能用于全量汇总。' if result.get('truncated') else ''))
        if section.code:
            fence = '`' * max(3, max((len(m) + 1 for m in re.findall(r'`+', section.code.content)), default=3))
            parts.append(f'{fence}{section.code.language}\n{section.code.content}\n{fence}')
    return '\n\n'.join(parts)
