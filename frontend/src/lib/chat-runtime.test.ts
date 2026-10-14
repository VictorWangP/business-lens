import {describe, it, expect} from 'vitest';
import {toRuntimeMessage} from './chat-runtime';
import type {Message} from '../types/chat';

const original: Message = {id:'assistant-1', conversation_id:'session-1', role:'assistant', content:'### 收入\n\n**10亿** [查询 Q1]', created_at:'2026-10-10T00:00:00Z',
  tool_calls:{chart:{type:'line', title:'销售', x_key:'month', y_keys:['revenue'], data:[{month:'2026-10',revenue:1000000000}]}, metrics:[{label:'收入',value:'10亿'}], query_results:[]},
  citations:[{id:'S1',doc_id:'doc-1',doc_name:'政策',chunk_index:0,content:'政策原文'}]};
describe('SSE messages to assistant-ui', () => {
  it('preserves Markdown and evidence and exposes stable chart/metric tool parts', () => {
    const result = toRuntimeMessage(original, true);
    expect(result.content).toEqual(expect.arrayContaining([
      {type:'text', text:original.content}, expect.objectContaining({type:'tool-call',toolCallId:'assistant-1:chart',toolName:'render_chart',args:{chart:original.tool_calls.chart}}),
      expect.objectContaining({toolName:'render_metrics'}),
    ]));
    expect(result.metadata.custom.appMessage).toBe(original);
    expect(result.status).toEqual({type:'running'});
    expect(toRuntimeMessage({...original, content:'更新正文'}).content[2]).toMatchObject({toolCallId:'assistant-1:chart'});
  });
  it.each(['completed','partial','failed','cancelled'])('keeps terminal state %s even while the transport finishes', status => {
    expect(toRuntimeMessage({...original,tool_calls:{...original.tool_calls,status}},true).status.type).toBe(
      ['failed','cancelled'].includes(status) ? 'incomplete' : 'complete');
  });
});
