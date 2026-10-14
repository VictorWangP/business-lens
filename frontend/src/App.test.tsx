import pauseFixture from './test/fixtures/agui-pause-resume.json';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppContent } from './App';
import { apiRequest } from './services/api';

const configs = {
  welcome_setting:{is_enabled:true, greeting:'你好', assistant_name:'业务助手', description:'欢迎提问', questions:['查看销售']},
  next_questions:{is_enabled:true}, voice_stt:{is_enabled:false}, voice_tts:{is_enabled:false},
  frequent_questions:{is_enabled:true,threshold:3},
  model_setting:{is_enabled:true,default_model:'model-a',available_models:[
    {id:'model-a',name:'模型 A',type:'llm'}, {id:'model-b',name:'模型 B',type:'llm'}, {id:'embed',name:'向量模型',type:'embedding'}]},
};
vi.mock('./context/ConfigContext', () => ({useConfig: () => ({configs, toggleConfig:vi.fn(), updateConfig:vi.fn()})}));
vi.mock('./context/AuthContext', () => {
  const user = {id:'u',username:'user'};
  const logout = vi.fn();
  return {useAuth: () => ({user,logout})};
});
vi.mock('./context/ThemeContext', () => ({useTheme: () => ({theme:'light',toggleTheme:vi.fn()})}));
vi.mock('./context/BookmarkContext', () => ({useBookmarks: () => ({bookmarks:[],isBookmarked:() => false,toggleBookmark:vi.fn(),removeBookmark:vi.fn()})}));
vi.mock('./services/api', () => ({apiRequest:vi.fn(),getToken:() => 'test-token'}));
// jsdom has no layout; give the real chart a fixed viewport instead of mocking chart rendering.
vi.mock('recharts', async importOriginal => ({
  ...await importOriginal<typeof import('recharts')>(),
  ResponsiveContainer: ({children}: {children:React.ReactElement<{width:number; height:number}>}) =>
    React.cloneElement(children, {width:640, height:288}),
}));

const requests: {controller:ReadableStreamDefaultController<Uint8Array>; options:RequestInit}[] = [];
beforeEach(() => {
  requests.length = 0;
  vi.mocked(apiRequest).mockImplementation(async (path:string) => {
    if (path.startsWith('/frequent-questions')) return [{id:'f1', question:'常问问题', count:3, last_asked_at:'2026-10-12T00:00:00Z'}];
    if (path === '/workspaces') return [{id:'w',name:'默认业务空间',version:1,status:'ready',kb_ids:['kb'],source_ids:[],unavailable_kb_ids:[],unavailable_source_ids:[]}];
    if (path === '/sessions') return [{id:'s1',title:'会话一',workspace_id:'w',scope_version:1},{id:'s2',title:'会话二',workspace_id:'w',scope_version:1}];
    if (path.includes('/messages')) return [];
    if (path === '/knowledge/bases' || path === '/data-sources') return [];
    return {};
  });
  vi.stubGlobal('fetch',vi.fn(async (_url, options) => {
    let controller:ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({start(value){controller=value;}});
    requests.push({controller,options});
    return new Response(stream,{headers:{'Content-Type':'text/event-stream'}});
  }));
});
afterEach(async () => {
  await act(async () => {for (const request of requests) {try {request.controller.close();} catch {}}});
});
async function push(index:number,event:unknown) {
  await act(async () => {requests[index].controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));});
}
async function start() {
  const user = userEvent.setup(); render(<AppContent />);
  await screen.findByText('会话一');
  await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith('/sessions/s1/messages'));
  await user.type(screen.getByRole('textbox',{name:'输入问题'}),'汇总销售');
  await user.click(screen.getByRole('button',{name:'发送问题'}));
  await waitFor(() => expect(requests).toHaveLength(1));
  return user;
}

const data={answer:{version:1,sections:[{title:'销售汇总',summary:'收入增长',query_id:'Q1',show_table:true}],suggestions:['查看成本明细','比较地区差异','查看销售口径']},queries:[{query_id:'q1',citation_id:'Q1',source_name:'销售数据',rows:[{month:'2026-10',revenue:10}],truncated:false,metrics:[{label:'合计收入',value:'10亿'}],chart:{type:'line',title:'月度收入趋势',x_key:'month',y_keys:['revenue'],data:[{month:'2026-10',revenue:10},{month:'2026-11',revenue:20}]}}],citations:[{id:'S1',doc_id:'doc1',doc_name:'销售政策',chunk_index:0,content:'政策原文'}]};
async function finish(){
 const input=JSON.parse(requests[0].options.body as string);
 for(const event of [
  {type:'TEXT_MESSAGE_START',messageId:'a0',role:'assistant'},
  {type:'TEXT_MESSAGE_CONTENT',messageId:'a0',delta:'## 1. 销售汇总\n\n**收入增长** [查询 Q1]'},
  {type:'TEXT_MESSAGE_END',messageId:'a0'},
  {type:'ACTIVITY_SNAPSHOT',messageId:'a0:business',activityType:'business-answer',content:data,replace:true},
  {type:'RUN_FINISHED',threadId:input.threadId,runId:input.runId,outcome:{type:'success'}}]) await push(0,event);
 await act(async()=>requests[0].controller.close());
}
describe('official AG-UI runtime and product UI',()=>{
 it('uses standard input and displays native text, exact table, chart, citations and three follow-ups',async()=>{
  const user=await start();const input=JSON.parse(requests[0].options.body as string);
  expect(input.threadId).toBe('s1');expect(input.forwardedProps).toMatchObject({model:'model-a',workspace_id:'w'});
  await push(0,{type:'RUN_STARTED',threadId:'s1',runId:input.runId});await finish();
  expect(await screen.findByRole('heading',{name:'1. 销售汇总'})).toBeVisible();
  expect(screen.getByRole('table')).toHaveTextContent('2026-10');
  expect(screen.getAllByText('月度收入趋势')).toHaveLength(1);
  expect(document.querySelector('.recharts-line')).toBeInTheDocument();
  for(const prompt of data.answer.suggestions)expect(screen.getByRole('button',{name:prompt})).toBeVisible();
  await user.click(screen.getByText('销售政策'));expect(screen.getByRole('dialog',{name:'销售政策'})).toHaveTextContent('政策原文');
 });
 it('preserves all tool operations in a collapsed process without exposing results',async()=>{
  const user=await start();const input=JSON.parse(requests[0].options.body as string);
  await push(0,{type:'RUN_STARTED',threadId:'s1',runId:input.runId});
  for(let i=0;i<2;i++)for(const event of [
   {type:'TOOL_CALL_START',toolCallId:`t${i}`,toolCallName:'execute_readonly_sql',parentMessageId:'a0'},
   {type:'TOOL_CALL_ARGS',toolCallId:`t${i}`,delta:'{}'},
   {type:'TOOL_CALL_END',toolCallId:`t${i}`},
   {type:'TOOL_CALL_RESULT',toolCallId:`t${i}`,messageId:`r${i}`,role:'tool',content:'{"status":"completed"}'}])await push(0,event);
  await finish();const summary=await screen.findByText('分析过程 · 完成');
  expect(summary.closest('details')).not.toHaveAttribute('open');await user.click(summary);
  expect(screen.getAllByText('开始执行 · 查询业务数据')).toHaveLength(2);
  expect(screen.getAllByText('执行结束 · 查询业务数据')).toHaveLength(2);
  expect(screen.queryByText('{"status":"completed"}')).not.toBeInTheDocument();
 });
 it('sends a follow-up through the native runtime',async()=>{
  const user=await start();const input=JSON.parse(requests[0].options.body as string);
  await push(0,{type:'RUN_STARTED',threadId:'s1',runId:input.runId});await finish();
  await user.click(await screen.findByRole('button',{name:'查看成本明细'}));
  await waitFor(()=>expect(requests).toHaveLength(2));
  const next=JSON.parse(requests[1].options.body as string);
  expect(next.messages[next.messages.length-1]).toMatchObject({role:'user',content:'查看成本明细'});
 });
 it('switches threads without cancelling persistent execution',async()=>{
  const user=await start();await user.click(screen.getByText('会话二'));
  await waitFor(()=>expect(apiRequest).toHaveBeenCalledWith('/sessions/s2/messages'));
  expect(vi.mocked(apiRequest).mock.calls.some(([path])=>path.includes('/cancel'))).toBe(false);
 });
 it('cancels persistent execution only through the stop action',async()=>{
  const user=await start();const input=JSON.parse(requests[0].options.body as string);
  await push(0,{type:'RUN_STARTED',threadId:'s1',runId:input.runId});
  await user.click(screen.getByRole('button',{name:'停止生成'}));
  await waitFor(()=>expect(apiRequest).toHaveBeenCalledWith(`/runs/${input.runId}/cancel`,{method:'POST'}));
 });
});

async function sendFixture(index:number, events:any[]) {
  const input=JSON.parse(requests[index].options.body as string);
  for(const event of events) await push(index,{...event,
    ...(['RUN_STARTED','RUN_FINISHED'].includes(event.type) ? {threadId:input.threadId,runId:input.runId}:{})});
  await act(async()=>requests[index].controller.close());
}

describe('official runtime durable recovery',()=>{
  it('resumes an interrupt using official hooks and self-contained backend replay',async()=>{
    const user=await start();await sendFixture(0,pauseFixture.first);
    const input=await screen.findByLabelText('使用哪个年度？');
    await user.type(input,'2026');await user.click(screen.getByRole('button',{name:'确认并继续'}));
    await waitFor(()=>expect(requests).toHaveLength(2));
    const request=JSON.parse(requests[1].options.body as string);
    expect(request.resume).toEqual([expect.objectContaining({status:'resolved',payload:'2026'})]);
    await sendFixture(1,pauseFixture.second);
    expect(await screen.findByText('按2026年分析。')).toBeVisible();
    expect(screen.queryByLabelText('使用哪个年度？')).not.toBeInTheDocument();
    expect(await screen.findByRole('button',{name:'发送问题'})).toBeVisible();
  });
  it('reconnects an in-flight run from archive through the native history adapter',async()=>{
    const original=vi.mocked(apiRequest).getMockImplementation();
    vi.mocked(apiRequest).mockImplementation(async(path,...args)=>{
      if(path==='/sessions/s1/messages')return [
        {id:'restored-user',conversation_id:'s1',role:'user',content:'分析销售',created_at:'2026-10-14T00:00:00Z'},
        {id:'restored-assistant',conversation_id:'s1',role:'assistant',content:'',tool_calls:{run_id:'persisted-run',status:'running'},created_at:'2026-10-14T00:00:01Z'}];
      return original!(path,...args);
    });
    render(<AppContent/>);await screen.findByText('会话一');
    await waitFor(()=>expect(requests).toHaveLength(1));
    const request=JSON.parse(requests[0].options.body as string);
    expect(request.messages).toEqual([expect.objectContaining({id:'restored-user',content:'分析销售'})]);
    await sendFixture(0,pauseFixture.second);
    expect(await screen.findByText('按2026年分析。')).toBeVisible();
    expect(screen.queryByLabelText('使用哪个年度？')).not.toBeInTheDocument();
  });
  it('appends an edited question and keeps the original conversation visible',async()=>{
    const user=await start();const input=JSON.parse(requests[0].options.body as string);
    await push(0,{type:'RUN_STARTED',threadId:'s1',runId:input.runId});await finish();
    await user.click(screen.getByTitle('编辑问题'));
    const editor=screen.getByRole('textbox',{name:'编辑问题内容'});
    await user.clear(editor);await user.type(editor,'修改后的销售问题');
    await user.click(screen.getByRole('button',{name:'保存并发送'}));
    await waitFor(()=>expect(requests).toHaveLength(2));
    expect(screen.getByText('汇总销售')).toBeVisible();
    expect(screen.getByText('修改后的销售问题')).toBeVisible();
  });
});
