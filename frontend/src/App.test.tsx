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
    return {ok:true,body:stream};
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
  await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith('/sessions/s1/messages',expect.anything()));
  await user.type(screen.getByRole('textbox',{name:'输入问题'}),'汇总销售');
  await user.click(screen.getByRole('button',{name:'发送问题'}));
  await waitFor(() => expect(requests).toHaveLength(1));
  return user;
}

describe('assistant-ui runtime with the existing SSE backend', () => {
  it('restores full execution events and query evidence inside the collapsed analysis process', async () => {
    const user = await start();
    await push(0, {type:'run_started',run_id:'run-detail',conversation_id:'s1',status:'running'});
    await push(0, {type:'tool_start',run_id:'run-detail',name:'execute_readonly_sql'});
    await push(0, {type:'tool_end',run_id:'run-detail',name:'execute_readonly_sql'});
    await push(0, {type:'tool_start',run_id:'run-detail',name:'execute_readonly_sql'});
    await push(0, {type:'tool_end',run_id:'run-detail',name:'execute_readonly_sql'});
    await push(0, {type:'query_result',run_id:'run-detail',query_id:'q-detail',citation_id:'Q1',source_name:'销售数据',retrieved_at:'2026-10-12T00:00:00Z',rows:[{revenue:10}],sql:'SELECT revenue FROM sales',parameters:{year:2026},truncated:false});
    await push(0, {type:'chunk',run_id:'run-detail',content:'收入为 10。'});
    await push(0, {type:'done',run_id:'run-detail',status:'completed',conversation_id:'s1'});
    const summary = await screen.findByText('分析过程 · 完成');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    await user.click(summary);
    expect(screen.getAllByText('开始执行 · 查询业务数据')).toHaveLength(2);
    expect(screen.getAllByText('执行结束 · 查询业务数据')).toHaveLength(2);
    await user.click(screen.getByText('查询 Q1 · 销售数据 · 1 行'));
    expect(screen.getByText('SELECT revenue FROM sales')).toBeVisible();
    expect(screen.getByText(/"year": 2026/)).toBeVisible();
    await user.click(screen.getByText('查看执行记录'));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith('/runs/run-detail'));
  });

  it('uses the configured default model and renders streamed Markdown, tools, charts and citation evidence once', async () => {
    const user = userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
    expect(screen.queryByRole('combobox',{name:'选择对话模型'})).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'快捷提问'})).toBeInTheDocument();
    await user.type(screen.getByRole('textbox',{name:'输入问题'}),'汇总销售{Enter}');
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(JSON.parse(requests[0].options.body as string).model).toBe('model-a');
    expect(screen.getByText('正在思考并准备回答…')).toBeInTheDocument();
    await push(0,{type:'tool_start',name:'execute_readonly_sql'});
    expect(screen.getByText('正在查询业务数据…')).toBeInTheDocument();
    await push(0,{type:'query_result',query_id:'q1',citation_id:'Q1',source_name:'销售数据',rows:[{month:'2026-10',revenue:10}],sql:'SELECT revenue FROM dataset'});
    await push(0,{type:'tool_call',metrics:[{label:'合计收入',value:'10亿'}],chart:{type:'line',title:'月度收入趋势',x_key:'month',y_keys:['revenue'],data:[{month:'2026-10',revenue:10}]}});
    await push(0,{type:'citations',items:[{id:'S1',doc_id:'doc1',doc_name:'销售政策',chunk_index:0,content:'政策原文'}]});
    await push(0,{type:'chunk',content:'### 销售汇总\n\n**收入增长** [查询 Q1]\n\n| 月份 | 收入 |\n| --- | --- |\n| 十月 | 10亿 |'});
    expect(await screen.findByRole('heading',{name:'销售汇总'})).toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveTextContent('十月');
    expect(screen.getAllByText('月度收入趋势')).toHaveLength(1);
    expect(screen.getByRole('button',{name:'切换为折线图'})).toHaveAttribute('aria-pressed','true');
    expect(document.querySelector('.recharts-line')).toBeInTheDocument();
    expect(screen.getByText('合计收入')).toBeInTheDocument();
    await user.click(screen.getByText('销售政策'));
    expect(screen.getByRole('dialog',{name:'销售政策'})).toHaveTextContent('政策原文');
    await user.click(screen.getByRole('button',{name:/^关闭$/}));
    await push(0,{type:'done',status:'completed',conversation_id:'s1'});
    await act(async () => requests[0].controller.close());
    expect(await screen.findByRole('button',{name:'发送问题'})).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'停止生成'})).not.toBeInTheDocument();
    expect(screen.getByText(/查询 Q1 · 销售数据/)).toBeInTheDocument();
  });

  it('cancels via the native button and ignores late frames from the cancelled request', async () => {
    const user = await start();
    await user.click(screen.getByRole('button',{name:'停止生成'}));
    expect(requests[0].options.signal.aborted).toBe(true);
    expect(screen.getByText('执行已停止')).toBeInTheDocument();
    await user.type(screen.getByRole('textbox',{name:'输入问题'}),'第二个问题');
    await user.click(screen.getByRole('button',{name:'发送问题'}));
    await waitFor(() => expect(requests).toHaveLength(2));
    await push(0,{type:'chunk',content:'不应该出现的迟到回答'});
    expect(screen.queryByText('不应该出现的迟到回答')).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'停止生成'})).toBeInTheDocument();
    await push(1,{type:'chunk',content:'第二个回答'}); await push(1,{type:'done',status:'completed',conversation_id:'s1'});
    await act(async () => requests[1].controller.close());
    expect(await screen.findByText('第二个回答')).toBeInTheDocument();
  });

  it('cancels before switching conversations and isolates late responses from the new thread', async () => {
    const user = await start();
    await user.click(screen.getByText('会话二'));
    expect(requests[0].options.signal.aborted).toBe(true);
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith('/sessions/s2/messages',expect.anything()));
    await push(0,{type:'chunk',content:'旧会话迟到结果'});
    expect(screen.queryByText('旧会话迟到结果')).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'发送问题'})).toBeInTheDocument();
  });
});

describe('native chat actions and navigation', () => {
  it('derives three suggestions from the answer message and preserves them when done has no duplicate payload', async () => {
    const user = await start();
    const questions = ['查看收入明细', '比较毛利变化', '说明统计口径'];
    await push(0, {type:'answer', content:'## 1. 收入趋势\n\n收入有所增长。',
      answer:{version:1,sections:[{title:'收入趋势',summary:'收入有所增长。'}],suggestions:questions}});
    expect(screen.queryByRole('button',{name:questions[0]})).not.toBeInTheDocument();
    await push(0, {type:'done',status:'completed',conversation_id:'s1'});
    await act(async () => requests[0].controller.close());
    expect(await screen.findByRole('heading',{name:'1. 收入趋势'})).toBeInTheDocument();
    for (const question of questions) expect(screen.getByRole('button',{name:question})).toBeInTheDocument();
    expect(screen.queryByText(/"sections"/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:questions[0]}));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(JSON.parse(requests[1].options.body as string).query).toBe(questions[0]);
    expect(screen.queryByRole('button',{name:questions[1]})).not.toBeInTheDocument();
  });

  it('sends welcome and follow-up suggestions through the selected runtime', async () => {
    const user = userEvent.setup(); render(<AppContent />);
    await screen.findByText('会话一');
    await user.click(screen.getByRole('button',{name:'查看销售'}));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(JSON.parse(requests[0].options.body as string).query).toBe('查看销售');
    await push(0,{type:'chunk',content:'销售回答'});
    await push(0,{type:'done',status:'completed',conversation_id:'s1',suggestions:['分析毛利']});
    await act(async () => requests[0].controller.close());
    await user.click(await screen.findByRole('button',{name:'分析毛利'}));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(JSON.parse(requests[1].options.body as string).query).toBe('分析毛利');
    expect(screen.getByText('销售回答')).toBeInTheDocument();
  });

  it('restores suggestions from historical messages when switching to a session', async () => {
    vi.mocked(apiRequest).mockImplementation(async (path:string) => {
      if (path.startsWith('/frequent-questions')) return [];
      if (path === '/workspaces') return [{id:'w',name:'默认业务空间',version:1,status:'ready',kb_ids:['kb'],source_ids:[],unavailable_kb_ids:[],unavailable_source_ids:[]}];
      if (path === '/sessions') return [{id:'s1',title:'会话一',workspace_id:'w',scope_version:1},{id:'s2',title:'会话二',workspace_id:'w',scope_version:1}];
      if (path === '/sessions/s2/messages') return [
        {id:'m1',conversation_id:'s2',role:'user',content:'历史提问',created_at:'2026-10-12T00:00:00Z'},
        {id:'m2',conversation_id:'s2',role:'assistant',content:'历史回答',tool_calls:{answer:{version:1,sections:[{title:'分析',summary:'历史回答'}],suggestions:['历史推荐问题','查看明细','比较差异']}},created_at:'2026-10-12T00:00:01Z'}
      ];
      if (path.includes('/messages')) return [];
      return {};
    });
    const user = userEvent.setup(); render(<AppContent />);
    await screen.findByText('会话一');
    await user.click(screen.getByText('会话二'));
    expect(await screen.findByRole('button',{name:'历史推荐问题'})).toBeInTheDocument();
  });

  it('uses native copy and editing while retaining the original linear conversation', async () => {
    const user = await start();
    await push(0,{type:'chunk',content:'原来的回答'});
    await push(0,{type:'done',status:'completed',conversation_id:'s1'});
    await act(async () => requests[0].controller.close());
    await user.click(screen.getByRole('button',{name:/^复制$/}));
    expect(await navigator.clipboard.readText()).toBe('汇总销售');
    expect(await screen.findByText('已复制')).toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'编辑'}));
    await user.clear(screen.getByRole('textbox',{name:'编辑问题内容'}));
    await user.type(screen.getByRole('textbox',{name:'编辑问题内容'}),'汇总毛利');
    await user.click(screen.getByRole('button',{name:'保存并发送'}));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(JSON.parse(requests[1].options.body as string).query).toBe('汇总毛利');
    expect(screen.getByText('汇总销售')).toBeInTheDocument();
    expect(screen.getByText('原来的回答')).toBeInTheDocument();
    expect(screen.getByText('汇总毛利')).toBeInTheDocument();
    expect(screen.queryByRole('textbox',{name:'编辑问题内容'})).not.toBeInTheDocument();
  });

  it('navigates to data management and preserves desktop collapse preferences', async () => {
    const user = userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
    await user.click(screen.getByRole('button',{name:'业务数据'}));
    expect(await screen.findByRole('heading',{name:'业务数据管理'})).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'业务数据'})).toHaveAttribute('aria-current','page');
    await user.click(screen.getByRole('button',{name:'折叠菜单栏'}));
    expect(localStorage.getItem('rag_sidebar_collapsed')).toBe('true');
    await user.click(screen.getByRole('button',{name:'展开或折叠菜单栏'}));
    expect(localStorage.getItem('rag_sidebar_collapsed')).toBe('false');
    await user.click(screen.getByRole('button',{name:'应用配置'}));
    expect(screen.queryByRole('button',{name:'导入业务数据'})).not.toBeInTheDocument();
  });
});

it('uses the native thread list for creation and keyboard switching', async () => {
  const previous=vi.mocked(apiRequest).getMockImplementation();
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === '/sessions' && options?.method === 'POST') return {id:'s3',title:'新建会话'};
    return previous(path,options);
  });
  const user=userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
  await user.click(screen.getByRole('button',{name:'会话一'}));
  await user.keyboard('{ArrowDown}');
  expect(screen.getByRole('button',{name:'会话二'})).toHaveFocus();
  await user.keyboard('{Enter}');
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith('/sessions/s2/messages',expect.anything()));
  await user.click(screen.getByRole('button',{name:'新建对话'}));
  expect(screen.getByRole('combobox',{name:'切换业务空间'})).toBeInTheDocument();
  expect(apiRequest).not.toHaveBeenCalledWith('/sessions',expect.objectContaining({method:'POST'}));
});

it('opens the mobile sidebar as a sheet and closes it after navigating', async () => {
  Object.defineProperty(window,'innerWidth',{configurable:true,writable:true,value:640});
  try {
    const user=userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
    await user.click(screen.getByRole('button',{name:'展开或折叠菜单栏'}));
    const menu=await screen.findByRole('dialog',{name:'主菜单'});
    await user.click(within(menu).getByRole('button',{name:'业务数据'}));
    expect(await screen.findByRole('heading',{name:'业务数据管理'})).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog',{name:'主菜单'})).not.toBeInTheDocument());
  } finally { Object.defineProperty(window,'innerWidth',{configurable:true,writable:true,value:1024}); }
});

it('shows real frequent counts and fills the composer without sending', async () => {
  const user=userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
  await user.click(screen.getByRole('button',{name:'快捷提问'}));
  expect(screen.getByRole('tab',{name:'常问'})).toHaveAttribute('aria-selected','true');
  await user.click(screen.getByRole('tab',{name:'收藏'}));
  expect(screen.getByRole('tabpanel',{name:'收藏'})).toHaveTextContent('暂无收藏问题');
  expect(screen.queryByRole('button',{name:'常问问题 3 次'})).not.toBeInTheDocument();
  await user.keyboard('{ArrowLeft}');
  expect(screen.getByRole('tab',{name:'常问'})).toHaveAttribute('aria-selected','true');
  const item=await screen.findByRole('button',{name:'常问问题 3 次'});
  await user.click(item);
  expect(screen.getByRole('textbox',{name:'输入问题'})).toHaveValue('常问问题');
  expect(requests).toHaveLength(0);
  await user.click(screen.getByRole('button',{name:'发送问题'}));
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(JSON.parse(requests[0].options.body as string).query).toBe('常问问题');
});

function mockBusinessSpaces() {
  let spaces = [
    {id:'w1',name:'销售空间',version:1,status:'ready',kb_ids:['kb1'],source_ids:['ds1'],unavailable_kb_ids:[],unavailable_source_ids:[]},
    {id:'w2',name:'空白空间',version:1,status:'empty',kb_ids:[],source_ids:[],unavailable_kb_ids:[],unavailable_source_ids:[]},
  ];
  const sessions = [
    {id:'biz1',title:'销售会话',workspace_id:'w1',scope_version:1},
    {id:'biz2',title:'其他空间会话',workspace_id:'w2',scope_version:0},
  ];
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    const body = options?.body ? JSON.parse(options.body as string) : {};
    if (path === '/workspaces' && options?.method === 'POST') {
      const created = {...body,id:'w3',version:1,status:body.kb_ids.length || body.source_ids.length ? 'ready' : 'empty',unavailable_kb_ids:[],unavailable_source_ids:[]};
      spaces = [...spaces,created]; return created;
    }
    if (path === '/workspaces') return spaces;
    if (path === '/knowledge/bases') return [{id:'kb1',name:'政策知识'}];
    if (path.endsWith('/documents')) return [];
    if (path === '/data-sources') return [{id:'ds1',name:'销售数据'}];
    if (path.startsWith('/frequent-questions')) return [];
    if (path.endsWith('/messages')) return path.includes('biz1') ? [{id:'old',conversation_id:'biz1',role:'assistant',content:'历史销售回答',created_at:'2026-10-12T00:00:00Z'}] : [];
    if (path === '/sessions') return sessions;
    if (path.startsWith('/workspaces/') && options?.method === 'PUT') {
      const id = path.split('/').pop();
      spaces = spaces.map(w => w.id === id ? {...w,...body,version:w.version+1,status:body.kb_ids.length || body.source_ids.length ? 'ready' : 'empty'} : w);
      return spaces.find(w => w.id === id);
    }
    return {};
  });
}

it('manages sources on the separate workspace page and keeps histories bound to different spaces', async () => {
  mockBusinessSpaces();
  const user=userEvent.setup(); render(<AppContent />);
  await screen.findByRole('button',{name:'销售会话'});
  expect(screen.queryByRole('button',{name:'其他空间会话'})).not.toBeInTheDocument();
  expect(screen.queryByText('生效知识库')).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.getByRole('combobox',{name:'切换业务空间'})).toHaveTextContent('销售空间');
  expect(screen.queryByText('业务空间：')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'业务空间'}));
  await screen.findByRole('heading',{name:'业务空间'});
  await user.click(screen.getByRole('button',{name:'编辑 销售空间'}));
  expect(await screen.findByRole('heading',{name:'编辑业务空间'})).toBeInTheDocument();
  await user.click(screen.getByRole('checkbox',{name:'销售数据'}));
  await user.click(screen.getByRole('button',{name:'保存'}));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith('/workspaces/w1',expect.objectContaining({method:'PUT',body:JSON.stringify({name:'销售空间',kb_ids:['kb1'],source_ids:[],version:1})})));
  await user.click(screen.getByRole('button',{name:'返回对话'}));
  expect(await screen.findByText('历史销售回答')).toBeVisible();
  expect(screen.getByText('业务空间配置已更新，后续提问将使用最新来源。')).toBeVisible();
  await user.click(screen.getByRole('combobox',{name:'切换业务空间'}));
  await user.click(screen.getByRole('option',{name:'空白空间'}));
  expect(await screen.findByRole('button',{name:'其他空间会话'})).toBeInTheDocument();
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith('/sessions/biz2/messages',expect.anything()));
  expect(screen.queryByText('历史销售回答')).not.toBeInTheDocument();
  expect(screen.getByText('当前空间尚未关联来源，请前往业务空间管理页配置。')).toBeVisible();
  expect(screen.getByRole('combobox',{name:'切换业务空间'})).toHaveTextContent('空白空间');
});

it('binds a new draft to the selected workspace and recovers a question after configuration', async () => {
  mockBusinessSpaces();
  const user=userEvent.setup(); render(<AppContent />); await screen.findByRole('button',{name:'销售会话'});
  await user.click(screen.getByRole('button',{name:'新建对话'}));
  await user.click(screen.getByRole('combobox',{name:'切换业务空间'}));
  await user.click(screen.getByRole('option',{name:'空白空间'}));
  await user.click(screen.getByRole('button',{name:'新建对话'}));
  await user.type(screen.getByRole('textbox',{name:'输入问题'}),'本月收入是多少？');
  await user.click(screen.getByRole('button',{name:'发送问题'}));
  expect(await screen.findByText('原问题：本月收入是多少？')).toBeVisible();
  expect(requests).toHaveLength(0);
  await user.click(screen.getByRole('button',{name:'配置业务空间'}));
  await user.click(screen.getByRole('checkbox',{name:'销售数据'}));
  await user.click(screen.getByRole('button',{name:'管理知识库'}));
  await user.click(screen.getByRole('button',{name:'返回业务空间'}));
  expect(screen.getByRole('checkbox',{name:'销售数据'})).toBeChecked();
  await user.click(screen.getByRole('button',{name:'保存'}));
  await user.click(screen.getByRole('button',{name:'返回对话'}));
  await user.click(screen.getByRole('button',{name:'继续提问'}));
  await waitFor(() => expect(requests).toHaveLength(1));
  const payload=JSON.parse(requests[0].options.body as string);
  expect(payload).toMatchObject({query:'本月收入是多少？',workspace_id:'w2'});
  expect(payload).not.toHaveProperty('kb_ids'); expect(payload).not.toHaveProperty('source_ids');
  await push(0,{type:'run_started',conversation_id:'created',workspace_id:'w2',scope_version:2});
  expect(screen.getByRole('combobox',{name:'切换业务空间'})).toHaveTextContent('空白空间');
});

it('creates a workspace with associations and starts a draft from its management page', async () => {
  mockBusinessSpaces();
  const user=userEvent.setup(); render(<AppContent />); await screen.findByRole('button',{name:'销售会话'});
  await user.click(screen.getByRole('button',{name:'业务空间'}));
  await user.click(screen.getByRole('button',{name:'新建业务空间'}));
  await user.type(screen.getByRole('textbox',{name:'空间名称'}),'产品支持');
  await user.click(screen.getByRole('checkbox',{name:'政策知识'}));
  await user.click(screen.getByRole('button',{name:'保存'}));
  await user.click(await screen.findByRole('button',{name:'在 产品支持 新建对话'}));
  expect(screen.getByRole('combobox',{name:'切换业务空间'})).toHaveTextContent('产品支持');
  expect(screen.getByRole('textbox',{name:'输入问题'})).toHaveValue('');
});


it('retains unsent composer text when visiting workspace configuration and returning', async () => {
  mockBusinessSpaces();
  const user=userEvent.setup(); render(<AppContent />); await screen.findByRole('button',{name:'销售会话'});
  await user.type(screen.getByRole('textbox',{name:'输入问题'}),'尚未发送的问题');
  await user.click(screen.getByRole('button',{name:'业务空间'}));
  await user.click(screen.getByRole('button',{name:'编辑 销售空间'}));
  await user.click(screen.getByRole('button',{name:'返回对话'}));
  expect(screen.getByRole('textbox',{name:'输入问题'})).toHaveValue('尚未发送的问题');
  expect(requests).toHaveLength(0);
});

it('defaults to the configured default LLM and allows temporarily switching models in a specific conversation', async () => {
  const user = userEvent.setup(); render(<AppContent />); await screen.findByText('会话一');
  const modelSwitcher = screen.getByRole('combobox', { name: '切换模型' });
  expect(modelSwitcher).toHaveTextContent(/模型 A/);

  // Switch model to 模型 B in 会话一
  await user.click(modelSwitcher);
  await user.click(await screen.findByRole('option', { name: /模型 B/ }));
  expect(modelSwitcher).toHaveTextContent(/模型 B/);
  expect(apiRequest).toHaveBeenCalledWith('/sessions/s1', expect.objectContaining({
    method: 'PUT',
    body: JSON.stringify({ model: 'model-b' }),
  }));

  // Send a question in 会话一 and verify request body uses model-b
  await user.type(screen.getByRole('textbox', { name: '输入问题' }), '测试模型B提问{Enter}');
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(JSON.parse(requests[0].options.body as string).model).toBe('model-b');
  await push(0, { type: 'done', status: 'completed', conversation_id: 's1' });
  await act(async () => requests[0].controller.close());

  // Switch to 会话二 (which has no override, should default to 模型 A)
  await user.click(screen.getByRole('button', { name: '会话二' }));
  expect(screen.getByRole('combobox', { name: '切换模型' })).toHaveTextContent(/模型 A/);

  // Switch back to 会话一 (should preserve 模型 B)
  await user.click(screen.getByRole('button', { name: '会话一' }));
  expect(screen.getByRole('combobox', { name: '切换模型' })).toHaveTextContent(/模型 B/);
});

