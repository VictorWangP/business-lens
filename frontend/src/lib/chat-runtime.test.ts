import {describe,it,expect} from 'vitest';
import {toRuntimeMessage} from './chat-runtime';
import type {Message} from '../types/chat';
describe('business archive projection',()=>{
  it('restores exact business data as a native data part',()=>{
    const presentation={answer:{version:1 as const,sections:[{title:'结果',summary:'已汇总'}],suggestions:['甲','乙','丙']},queries:[]};
    const message:Message={id:'a',conversation_id:'t',role:'assistant',content:'## 1. 结果',created_at:'2026-10-14T00:00:00Z',tool_calls:{presentation}};
    expect(toRuntimeMessage(message).content).toEqual([{type:'text',text:'## 1. 结果'},{type:'data',name:'agui-activity/business-answer',data:presentation}]);
  });
});

it('restores query arguments and result summaries from history',()=>{
  const message:Message={id:'a',conversation_id:'t',role:'assistant',content:'',created_at:'2026-10-14T00:00:00Z',
    tool_calls:{execution_events:[{type:'tool_start',name:'execute_readonly_sql',tool_id:'sql',args:{source_id:'sales',sql:'SELECT * FROM dataset'}},
      {type:'tool_end',name:'execute_readonly_sql',tool_id:'sql',result:{status:'failed',error:'无效字段'}}]}};
  expect(toRuntimeMessage(message).content?.[1]).toMatchObject({type:'tool-call',args:{source_id:'sales',sql:'SELECT * FROM dataset'},result:{status:'failed',error:'无效字段'}});
});

it('restores requires-action interrupt status and agui metadata for paused assistant messages',()=>{
  const message:Message={id:'a-int',conversation_id:'t',role:'assistant',content:'',created_at:'2026-10-14T00:00:00Z',
    tool_calls:{status:'paused',interrupts:[{id:'int-1',message:'请提供年份'}]}};
  const runtimeMsg = toRuntimeMessage(message);
  expect(runtimeMsg.status).toEqual({type:'requires-action',reason:'interrupt'});
  expect(runtimeMsg.metadata?.custom).toEqual(expect.objectContaining({
    status:'paused',
    agui:{interrupts:[{id:'int-1',message:'请提供年份'}]}
  }));
});

