import { fromMarkdown } from 'mdast-util-from-markdown';

// Migration boundary for legacy free-form messages. New answers are validated
// server-side; code is allowed only when explicitly requested by the user.
export function cleanAssistantAnswer(text: string, userQuery = ''): string {
  const requestsCode = /(?:代码|教程|绘图指南)/.test(userQuery) &&
    !/(?:不要|无需|不用|不需要|不必|别).{0,12}(?:代码|教程|指南)/.test(userQuery);
  if (requestsCode) return text;
  const ranges: [number, number][] = [];
  function visit(node: any) {
    if (node.type === 'code' || node.type === 'html') {
      ranges.push([node.position.start.offset, node.position.end.offset]);
    } else {
      node.children?.forEach(visit);
    }
  }
  visit(fromMarkdown(text));
  for (const [start, end] of ranges.sort((a, b) => b[0] - a[0])) text = text.slice(0, start) + text.slice(end);
  return text.replace(/\n{3,}/g, '\n\n').trim();
}
