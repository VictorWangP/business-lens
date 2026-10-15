import React from 'react';
import {render,screen,waitFor,act,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {apiRequest} from '../../services/api';
import {FeedbackView} from './FeedbackView';
import {FeedbackProcessDialog} from './FeedbackProcessDialog';
import {FeedbackButton} from './FeedbackButton';
import {FeedbackProvider} from '../../context/FeedbackContext';
import type {FeedbackDetail} from '../../types/feedback';
import type {Message} from '../../types/chat';
vi.mock('../../services/api',()=>({apiRequest:vi.fn()}));
vi.mock('../../context/AuthContext',()=>{const user={id:'u',username:'张经理'};return {useAuth:()=>({user})};});
const detail:FeedbackDetail={id:'f1',user:{id:'u',name:'张经理'},question:'本月账龄',created_at:'2026-10-13T03:00:00Z',status:'pending',version:1,reason:'data_error',user_comment:'请核对金额',processing_note:'',last_handled_by:null,last_handled_at:null,original_deleted:false,
  evidence_snapshot:{schema_version:2,answer:{content:'账龄主要集中在 30–60 天。'},presentation:{answer:{version:1,sections:[],suggestions:[]},queries:[]},context:{question_message_id:'q1',public_history:[],clarifications:[],truncated:false,kind:'public_archive'},resource:{workspace_id:'w',workspace_name:'经营分析',scope_version:1,source_ids:[]},execution:{run_id:'r1',assistant_message_id:'a1',model:'test-model',status:'completed',created_at:'2026-10-13T03:00:00Z',finished_at:null},completeness:{missing_fields:[],warnings:[]}},
  history:[{version:1,action:'created',actor_id:'u',actor_name:'张经理',from_status:null,to_status:'pending',old_note:'',new_note:'',created_at:'2026-10-13T03:00:00Z'}]};
const answer:Message={id:'a1',conversation_id:'s1',role:'assistant',content:'账龄主要集中在 30–60 天。',created_at:'2026-10-13T03:00:01Z',tool_calls:{run_id:'r1',status:'completed'}};
const eligible={message_id:'a1',run_id:'r1',run_status:'completed',eligible:true,ineligible_reason:null,question_message_id:'q1',question_preview:'本月账龄',feedback:null};
beforeEach(()=>vi.resetAllMocks());
afterEach(()=>vi.useRealTimers());
async function choose(label:string,value:string){const user=userEvent.setup();await user.click(screen.getByRole('combobox',{name:label}));await user.click(await screen.findByRole('option',{name:value}));}

it('loads summaries once for the session, submits reason and comment and restores feedback status',async()=>{
  const user=userEvent.setup();
  vi.mocked(apiRequest).mockImplementation(async(path,options)=>{
    if(path==='/sessions/s1/feedback-context')return {items:[eligible]};
    if(options?.method==='POST')return {id:'f1',message_id:'a1',status:'pending',created_at:detail.created_at};
    throw new Error(path);
  });
  render(<FeedbackProvider sessionId="s1"><FeedbackButton message={answer}/></FeedbackProvider>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'反馈错误'})).toBeEnabled());
  await user.click(screen.getByRole('button',{name:'反馈错误'}));
  expect(screen.getByText('本月账龄')).toBeInTheDocument();
  await choose('反馈原因','其他');
  expect(screen.getByRole('button',{name:'提交反馈'})).toBeDisabled();
  await user.type(screen.getByRole('textbox',{name:'补充说明（必填）'}),'请核查范围');
  await user.click(screen.getByRole('button',{name:'提交反馈'}));
  expect(await screen.findByRole('button',{name:'已反馈 · 待处理'})).toBeDisabled();
  expect(apiRequest).toHaveBeenCalledWith('/messages/a1/feedback',expect.objectContaining({body:JSON.stringify({reason:'other',comment:'请核查范围'})}));
  expect(vi.mocked(apiRequest).mock.calls.filter(([path])=>path==='/sessions/s1/feedback-context')).toHaveLength(1);
});

it('hides feedback for unfinished runs and clears another session summaries',async()=>{
  vi.mocked(apiRequest).mockResolvedValue({items:[{...eligible,feedback:{id:'f1',message_id:'a1',status:'resolved',created_at:detail.created_at}}]});
  const view=render(<FeedbackProvider sessionId="s1"><FeedbackButton message={answer}/></FeedbackProvider>);
  expect(await screen.findByRole('button',{name:'已反馈 · 已处理'})).toBeInTheDocument();
  let resolve:(value:unknown)=>void;
  vi.mocked(apiRequest).mockImplementation(()=>new Promise(done=>{resolve=done;}));
  view.rerender(<FeedbackProvider sessionId="s2"><FeedbackButton message={answer}/></FeedbackProvider>);
  expect(screen.queryByRole('button',{name:'已反馈 · 已处理'})).not.toBeInTheDocument();
  await act(async()=>resolve({items:[]}));
  view.rerender(<FeedbackProvider sessionId="s2"><FeedbackButton message={{...answer,tool_calls:{run_id:'r1',status:'running'}}}/></FeedbackProvider>);
  expect(screen.queryByRole('button',{name:'反馈错误'})).not.toBeInTheDocument();
});

it('preserves a failed submission and confirms discarding changes',async()=>{
  const user=userEvent.setup();
  vi.mocked(apiRequest).mockImplementation(async(path)=>{if(path.includes('/sessions/'))return {items:[eligible]};throw new Error('反馈服务不可用');});
  render(<FeedbackProvider sessionId="s1"><FeedbackButton message={answer}/></FeedbackProvider>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'反馈错误'})).toBeEnabled());
  await user.click(screen.getByRole('button',{name:'反馈错误'}));
  await user.type(screen.getByRole('textbox',{name:'补充说明（可选）'}),'原始草稿');
  await user.click(screen.getByRole('button',{name:'提交反馈'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('反馈服务不可用');
  expect(screen.getByRole('textbox',{name:'补充说明（可选）'})).toHaveValue('原始草稿');
  await user.click(screen.getByRole('button',{name:'取消'}));
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'放弃修改'}));
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('requires a completion note and saves with the loaded version',async()=>{
  const user=userEvent.setup(),onSaved=vi.fn();vi.mocked(apiRequest).mockResolvedValue(detail);
  render(<FeedbackProcessDialog id="f1" onClose={vi.fn()} onSaved={onSaved} onForbidden={vi.fn()}/>);
  expect(await screen.findByText('账龄主要集中在 30–60 天。')).toBeInTheDocument();
  await choose('处理状态','已处理');
  expect(screen.getByRole('button',{name:'确认'})).toBeDisabled();
  await user.type(screen.getByRole('textbox',{name:'处理备注（必填）'}),'已核实，待修复');
  await user.click(screen.getByRole('button',{name:'确认'}));
  await waitFor(()=>expect(onSaved).toHaveBeenCalledOnce());
  expect(apiRequest).toHaveBeenCalledWith('/feedback/f1',expect.objectContaining({method:'PATCH',body:JSON.stringify({status:'resolved',processing_note:'已核实，待修复',expected_version:1})}));
});

it('keeps draft on conflict and requires explicit reload before retrying',async()=>{
  const user=userEvent.setup(),onSaved=vi.fn();
  vi.mocked(apiRequest).mockResolvedValueOnce(detail).mockRejectedValueOnce(Object.assign(new Error('版本冲突'),{status:409})).mockResolvedValueOnce({...detail,version:2,processing_note:'他人的处理备注'}).mockResolvedValueOnce(detail);
  render(<FeedbackProcessDialog id="f1" onClose={vi.fn()} onSaved={onSaved} onForbidden={vi.fn()}/>);
  await screen.findByText('本月账龄');
  await user.type(screen.getByRole('textbox',{name:'处理备注'}),'保留本地核查');
  await user.click(screen.getByRole('button',{name:'确认'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('其他处理人更新');
  expect(screen.getByRole('textbox',{name:'处理备注'})).toHaveValue('保留本地核查');
  expect(screen.getByRole('button',{name:'确认'})).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'重新加载记录（保留草稿）'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'确认'})).toBeEnabled());
  expect(screen.getByText('他人的处理备注')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'确认'}));
  await waitFor(()=>expect(onSaved).toHaveBeenCalled());
  expect(apiRequest).toHaveBeenLastCalledWith('/feedback/f1',expect.objectContaining({body:JSON.stringify({status:'pending',processing_note:'保留本地核查',expected_version:2})}));
});

it('searches on enter, combines filters and resets pagination',async()=>{
  const user=userEvent.setup();vi.mocked(apiRequest).mockResolvedValue({items:[detail],total:21,page:1,page_size:10});
  render(<FeedbackView onForbidden={vi.fn()}/>);
  await screen.findByText('张经理');
  await user.click(screen.getByRole('button',{name:'下一页'}));
  await waitFor(()=>expect(apiRequest).toHaveBeenLastCalledWith(expect.stringContaining('page=2'),expect.anything()));
  await user.type(screen.getByRole('textbox',{name:'搜索问题'}),'账龄{Enter}');
  await waitFor(()=>expect(apiRequest).toHaveBeenLastCalledWith(expect.stringContaining('page=1'),expect.anything()));
  const path=String(vi.mocked(apiRequest).mock.calls[vi.mocked(apiRequest).mock.calls.length-1]?.[0]);
  expect(new URLSearchParams(path.split('?')[1]).get('question')).toBe('账龄');
  await choose('筛选状态','待处理');
  await waitFor(()=>expect(apiRequest).toHaveBeenLastCalledWith(expect.stringContaining('status=pending'),expect.anything()));
});

it('clears management data and exits after permission revocation',async()=>{
  const onForbidden=vi.fn();vi.mocked(apiRequest).mockRejectedValue(Object.assign(new Error('无回复校对权限'),{status:403}));
  render(<FeedbackView onForbidden={onForbidden}/>);
  await waitFor(()=>expect(onForbidden).toHaveBeenCalled());
  expect(screen.queryByText('张经理')).not.toBeInTheDocument();
});
