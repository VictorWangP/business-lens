"""One validated delivery contract; tool evidence never becomes answer source code."""
import json
import re
from typing import Literal

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
    summary: str = Field(min_length=1, max_length=6000, description='业务结论、口径和引用。不得包含代码、绘图指南、图表配置或工具原始数据。')
    query_id: str | None = None
    show_table: bool = False
    code: CodeExample | None = None


    @field_validator('summary')
    @classmethod
    def prose_only(cls, text):
        if any(token.type in {'fence','code_block','html_block','heading_open','table_open'} or
            any(child.type == 'html_inline' for child in (token.children or [])) for token in markdown.parse(text)):
            raise ValueError('业务结论不得包含源码、标题、HTML 或表格')
        return text


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)
    version: Literal[1] = 1
    sections: list[AnswerSection] = Field(min_length=1, max_length=12)
    suggestions: list[str] = Field(max_length=3)


    @field_validator('suggestions')
    @classmethod
    def distinct_questions(cls, items):
        items = [item.strip() for item in items]
        if len(set(items)) != len(items) or any(not item or len(item)>200 or '\n' in item for item in items):
            raise ValueError('延伸问题必须非空且不同')
        return items


class SuggestedAnswer(FinalAnswer):
    suggestions: list[str] = Field(min_length=3, max_length=3)


class PlainAnswer(FinalAnswer):
    suggestions: list[str] = Field(max_length=0)


def requests_code(query: str) -> bool:
    return bool(re.search(r'代码|教程|绘图指南', query)) and not bool(
        re.search(r'(?:不要|无需|不用|不需要|不必|别).{0,12}(?:代码|教程|指南)', query))


def parse_answer(raw: str, *, enabled: bool, allow_code: bool, queries: list[dict], citations: dict) -> FinalAnswer:
    try:
        answer = FinalAnswer.model_validate_json(raw)
        known_queries = {q['citation_id'] for q in queries}
        for section in answer.sections:
            section.title = re.sub(r'^\d+[.、．)]\s*', '', section.title.strip())
            title_tokens = markdown.parse(section.title)
            if not section.title or '\n' in section.title or '\r' in section.title or any(t.type != 'inline' and t.type not in {'paragraph_open', 'paragraph_close'} for t in title_tokens):
                raise ValueError('title 必须为单行文本')
            if not section.summary.strip():
                raise ValueError('summary 不能为空')
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


def render_answer(answer: FinalAnswer) -> str:
    """Render prose only; exact tables and charts remain native data parts."""
    def cell(value):
        return str(value if value is not None else '').replace('\\', '\\\\').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;').replace('`', '\\`').replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
    parts = []
    for index, section in enumerate(answer.sections, 1):
        title = re.sub(r'^\d+[.、．)]\s*', '', section.title)
        parts.extend([f'## {index}. {cell(title)}', section.summary])
        if section.code:
            fence = '`' * max(3, max((len(m) + 1 for m in re.findall(r'`+', section.code.content)), default=3))
            parts.append(f'{fence}{section.code.language}\n{section.code.content}\n{fence}')
    return '\n\n'.join(parts)
