import { describe, expect, it } from 'vitest';
import { cleanAssistantAnswer } from './answer-presentation';

describe('legacy answer migration by Markdown node type', () => {
  it.each([
    '```mermaid\nxychart-beta\nline [1,2]\n```',
    '~~~python\nimport matplotlib.pyplot as plt\n~~~',
    '```json\n{"data":[1,2]}\n```',
    '```unknown-language\nany future plotting syntax\n```',
    '    xychart-beta\n    line [1,2]',
  ])('removes unsolicited source regardless of its language: %s', block => {
    expect(cleanAssistantAnswer(`收入下降。\n\n${block}\n\n继续分析。`)).toBe('收入下降。\n\n继续分析。');
  });
  it('preserves business Markdown, tables and inline field names', () => {
    const answer='## 收入\n\n**增长** [查询 Q1]，字段为 `revenue`。\n\n| 月份 | 收入 |\n| --- | --- |\n| 一月 | 10 |';
    expect(cleanAssistantAnswer(answer)).toBe(answer);
  });
  it('preserves deliberately requested code but respects negation', () => {
    const answer='示例：\n\n```python\nprint(1)\n```';
    expect(cleanAssistantAnswer(answer,'请提供 Python 代码')).toBe(answer);
    expect(cleanAssistantAnswer(answer,'不需要代码')).toBe('示例：');
  });
});
