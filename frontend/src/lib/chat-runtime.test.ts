import {describe,it,expect} from 'vitest';
import {toRuntimeMessage} from './chat-runtime';
import type {Message} from '../types/chat';
describe('business archive projection',()=>{
  it('restores exact business data as a native data part',()=>{
    const presentation={answer:{version:1 as const,sections:[{title:'结果',summary:'已汇总'}],suggestions:['甲','乙','丙']},queries:[],citations:[]};
    const message:Message={id:'a',conversation_id:'t',role:'assistant',content:'## 1. 结果',created_at:'2026-10-14T00:00:00Z',tool_calls:{presentation}};
    expect(toRuntimeMessage(message).content).toEqual([{type:'text',text:'## 1. 结果'},{type:'data',name:'agui-activity/business-answer',data:presentation}]);
  });
});
