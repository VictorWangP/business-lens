import { WorkspacesView, type Workspace } from './components/workspaces/WorkspacesView';
import { FeedbackProvider } from './context/FeedbackContext';
import { FeedbackView } from './components/feedback/FeedbackView';
import React, { useState, useEffect, useMemo } from 'react';
import {useAuiState} from '@assistant-ui/react';
import {ChatRuntimeProvider} from './components/chat/ChatRuntimeProvider';
import {fromRuntimeMessage} from './lib/chat-runtime';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { ThreadList } from './components/chat/ThreadList';
import { Thread } from './components/chat/Thread';
import { AppConfigView } from './components/settings/AppConfigView';
import type { DataSource } from './components/data/DataSourcesPanel';
import { DataSourcesView } from './components/data/DataSourcesView';
import { KnowledgeView } from './components/knowledge/KnowledgeView';
import { AuthModal } from './components/auth/AuthModal';
import { useConfig } from './context/ConfigContext';
import { createAudioAdapters } from './lib/audio-adapters';
import { toast } from 'sonner';
import { Button } from './components/ui/button';
import { SidebarProvider } from './components/ui/sidebar';
import { Toaster } from './components/ui/sonner';
import { TooltipProvider } from './components/ui/tooltip';
import { useAuth } from './context/AuthContext';
import { Conversation } from './types/chat';
import { KnowledgeBase } from './types/knowledge';
import { apiRequest } from './services/api';

export function AppContent() {
  const { user } = useAuth();
  const { configs } = useConfig();
  const [selectedModel, setSelectedModel] = useState('');
  const [draftModel, setDraftModel] = useState('');

  const availableLlmModels = useMemo(() =>
    configs?.model_setting?.available_models.filter(m => m.type !== 'embedding') || [],
    [configs]
  );
  const defaultModelId = configs?.model_setting?.default_model || '';
  const [currentTab, setCurrentTab] = useState<string>('chat');
  useEffect(() => { if (currentTab === 'feedback' && user?.role !== 'feedback_admin') setCurrentTab('chat'); }, [user?.role, currentTab]);
  const audioAdapters = useMemo(() => createAudioAdapters(message => toast.error(message), {
    voiceName: configs?.voice_tts?.voice_name,
    speed: configs?.voice_tts?.speed,
  }), [configs?.voice_tts?.voice_name, configs?.voice_tts?.speed]);

  // 侧边栏与会话列表折叠状态（优先从 localStorage 读取记忆）
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('rag_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const [threadListCollapsed, setThreadListCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('rag_threadlist_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const toggleThreadList = () => {
    setThreadListCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('rag_threadlist_collapsed', String(next));
      } catch {}
      return next;
    });
  };

  // 对话与会话状态
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 联动当前会话模型或全局默认模型
  useEffect(() => {
    if (activeSessionId) {
      const session = conversations.find(c => c.id === activeSessionId);
      if (session?.model && availableLlmModels.some(m => m.id === session.model)) {
        setSelectedModel(session.model);
      } else if (defaultModelId && availableLlmModels.some(m => m.id === defaultModelId)) {
        setSelectedModel(defaultModelId);
      } else if (availableLlmModels.length > 0) {
        setSelectedModel(availableLlmModels[0].id);
      } else {
        setSelectedModel('');
      }
    } else {
      if (draftModel && availableLlmModels.some(m => m.id === draftModel)) {
        setSelectedModel(draftModel);
      } else if (defaultModelId && availableLlmModels.some(m => m.id === defaultModelId)) {
        setSelectedModel(defaultModelId);
      } else if (availableLlmModels.length > 0) {
        setSelectedModel(availableLlmModels[0].id);
      } else {
        setSelectedModel('');
      }
    }
  }, [activeSessionId, conversations, availableLlmModels, defaultModelId, draftModel]);

  const handleModelChange = (modelId: string) => {
    setSelectedModel(modelId);
    if (activeSessionId) {
      setConversations(items => items.map(c => c.id === activeSessionId ? { ...c, model: modelId } : c));
      void apiRequest(`/sessions/${activeSessionId}`, {
        method: 'PUT',
        body: JSON.stringify({ model: modelId }),
      }).catch(err => console.error('更新会话模型失败', err));
    } else {
      setDraftModel(modelId);
    }
  };

  useEffect(() => () => audioAdapters.dispose(), [audioAdapters, currentTab, activeSessionId, user,
    configs?.voice_stt?.is_enabled, configs?.voice_tts?.is_enabled]);

  // 知识库状态
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeWarning, setScopeWarning] = useState('');
  const [pendingQuestion, setPendingQuestion] = useState('');
  const [draftSequence, setDraftSequence] = useState(0);
  const [editRequest, setEditRequest] = useState<{id: string; sequence: number} | null>(null);
  const workspaceEpoch = React.useRef(0);
  const activeWorkspace = workspaces.find(w => w.id === workspaceId);
  const activeConversation = conversations.find(c => c.id === activeSessionId);
  const selectedKbIds = activeWorkspace?.kb_ids || [];
  const selectedSourceIds = activeWorkspace?.source_ids || [];
  const workspaceWarning = scopeWarning || (!workspaceId ? '请选择业务空间后提问。' : !activeWorkspace ? '绑定的业务空间不可用，请在可用空间新建对话。' :
    activeWorkspace.status === 'invalid' ? '当前空间存在不可用来源，请前往业务空间管理页检查配置。' :
    !selectedKbIds.length && !selectedSourceIds.length ? '当前空间尚未关联来源，请前往业务空间管理页配置。' :
    activeConversation?.scope_version && activeConversation.scope_version !== activeWorkspace.version ? '业务空间配置已更新，后续提问将使用最新来源。' : '');
  const workspaceNeedsSetup = !activeWorkspace || activeWorkspace.status === 'invalid' || (!selectedKbIds.length && !selectedSourceIds.length);

  useEffect(() => {
    let cancelled = false;
    workspaceEpoch.current += 1;
    setScopeReady(false);
    setConversations([]); setActiveSessionId(null);
    setKnowledgeBases([]); setDataSources([]); setWorkspaces([]); setWorkspaceId('');
    setPendingQuestion(''); setScopeWarning(''); setEditRequest(null);
    setCurrentTab('chat'); setDraftSequence(n => n + 1);
    if (user) {
      Promise.all([
        apiRequest<Conversation[]>('/sessions'), apiRequest<KnowledgeBase[]>('/knowledge/bases'),
        apiRequest<DataSource[]>('/data-sources'), apiRequest<Workspace[]>('/workspaces'),
      ]).then(([sessions, kbs, sources, spaces]) => {
        if (cancelled) return;
        setConversations(sessions); setKnowledgeBases(kbs); setDataSources(sources); setWorkspaces(spaces);
        const first = sessions[0];
        let remembered = '';
        try { remembered = localStorage.getItem(`rag_workspace:${user.id}`) || ''; } catch {}
        const fallback = spaces.find(w => w.id === remembered) || spaces.find(w => w.name === '默认业务空间') || spaces[0];
        setWorkspaceId(first ? first.workspace_id || '' : fallback?.id || '');
        setActiveSessionId(first?.id || null); setScopeReady(true);
      }).catch(error => { if (!cancelled) setScopeWarning('加载业务空间失败：' + error.message + '。请刷新重试。'); });
    }
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  useEffect(() => {
    if (!scopeReady || !user || (currentTab !== 'chat' && currentTab !== 'workspaces')) return;
    let cancelled = false;
    const epoch = workspaceEpoch.current;
    Promise.all([apiRequest<Workspace[]>('/workspaces'), apiRequest<KnowledgeBase[]>('/knowledge/bases'), apiRequest<DataSource[]>('/data-sources')])
      .then(([spaces, kbs, sources]) => {
        if (cancelled || epoch !== workspaceEpoch.current) return;
        setWorkspaces(spaces); setKnowledgeBases(kbs); setDataSources(sources); setScopeWarning('');
      }).catch(error => { if (!cancelled) setScopeWarning('刷新业务空间失败：' + error.message); });
    return () => { cancelled = true; };
  }, [currentTab, scopeReady, user]);

  useEffect(() => {
    if (!scopeReady || !user || !workspaceId) return;
    try { localStorage.setItem(`rag_workspace:${user.id}`, workspaceId); } catch {}
  }, [workspaceId, scopeReady, user]);

  useEffect(() => {
    if (!scopeReady || !user) return;
    let active = true;
    const controller = new AbortController();
    const refresh = () => { const epoch = workspaceEpoch.current; void apiRequest<Workspace[]>('/workspaces', {signal:controller.signal})
      .then(spaces => {if (active && epoch === workspaceEpoch.current) setWorkspaces(spaces);}).catch(() => {}); };
    const timer = window.setInterval(refresh, 10000);
    window.addEventListener('focus',refresh);
    return () => {active=false; controller.abort(); window.clearInterval(timer); window.removeEventListener('focus',refresh);};
  }, [scopeReady, user]);

  const openWorkspaceConfig = () => {
    setEditRequest(current => ({id:workspaceId, sequence:(current?.sequence || 0) + 1}));
    setCurrentTab('workspaces');
  };
  const startWorkspaceConversation = (id:string) => {
    setActiveSessionId(null);setWorkspaceId(id);setPendingQuestion('');setScopeWarning('');
    setDraftSequence(n=>n+1);setCurrentTab('chat');setDraftModel('');
  };

  // A draft is bound to the workspace currently selected in the session list.
  const handleNewSession = async () => {
    if (!scopeReady) return;
    startWorkspaceConversation(workspaceId);
  };

  // 删除会话
  const handleDeleteSession = async (id: string) => {
    try {
      await apiRequest(`/sessions/${id}`, { method: 'DELETE' });
      const filtered = conversations.filter((c) => c.id !== id);
      setConversations(filtered);
      if (activeSessionId === id) {
        const next = filtered.find(conversation => conversation.workspace_id === workspaceId);
        setActiveSessionId(next?.id || null);
        if (next) setWorkspaceId(next.workspace_id || '');
        setPendingQuestion(''); setScopeWarning(''); setDraftSequence(n => n + 1);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除会话失败');
    }
  };

  // 重命名会话
  const handleRenameSession = async (id: string, newTitle: string) => {
    try {
      const updated = await apiRequest<Conversation>(`/sessions/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ title: newTitle }),
      });
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c))
      );
    } catch (e) {
      console.error('重命名会话失败', e);
    }
  };

  // 置顶/取消置顶会话
  const handleTogglePinSession = async (id: string) => {
    try {
      const target = conversations.find((c) => c.id === id);
      if (!target) return;
      const nextPinned = !Boolean(target.is_pinned);
      const updated = await apiRequest<Conversation>(`/sessions/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_pinned: nextPinned }),
      });

      setConversations((prev) => {
        const nextList = prev.map((c) =>
          c.id === id ? { ...c, is_pinned: updated.is_pinned } : c
        );
        return [...nextList].sort((a, b) => {
          if (Boolean(a.is_pinned) !== Boolean(b.is_pinned)) {
            return a.is_pinned ? -1 : 1;
          }
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        });
      });
    } catch (e) {
      console.error('切换置顶状态失败', e);
    }
  };

  const handleSelectSession = async (id:string) => {
    const session=conversations.find(item=>item.id===id);
    if (!session) return;
    setActiveSessionId(id);setWorkspaceId(session.workspace_id || '');setPendingQuestion('');setScopeWarning('');
  };

  const handleSelectWorkspace = (id: string) => {
    if (!scopeReady || id === workspaceId || !workspaces.some(workspace => workspace.id === id)) return;
    const nextConversation = conversations
      .filter(conversation => conversation.workspace_id === id)
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
    if (nextConversation) {
      void handleSelectSession(nextConversation.id);
      return;
    }
    startWorkspaceConversation(id);
  };

  const handleWorkspaceNoticeAction = () => openWorkspaceConfig();
  const threadList={threadId:activeSessionId || undefined,
    threads:conversations.filter(c=>c.workspace_id===workspaceId).map(c=>({id:c.id,status:'regular' as const,title:c.title})),
    onSwitchToThread:async (id:string)=>{await handleSelectSession(id);return {messages:[]};},
    onSwitchToNewThread:handleNewSession,onRename:handleRenameSession,onDelete:handleDeleteSession};
  const onSettled=(id:string)=>{
    if (!activeSessionId) setActiveSessionId(id);
    void apiRequest<Conversation[]>('/sessions').then(setConversations).catch(()=>{});
  };

  return (
    <ChatRuntimeProvider key={`${user?.id || 'anonymous'}:${activeSessionId || `draft:${draftSequence}`}`}
      sessionId={activeSessionId} workspaceId={workspaceId} model={selectedModel} disabled={!scopeReady || workspaceNeedsSetup}
      adapters={{speech:configs?.voice_tts?.is_enabled ? audioAdapters.speech:undefined,
        dictation:configs?.voice_stt?.is_enabled ? audioAdapters.dictation:undefined}}
      threadList={threadList} onSettled={onSettled}>
      <RuntimeFeedbackProvider sessionId={activeSessionId}>
      <TooltipProvider delayDuration={300}>
      <SidebarProvider open={!sidebarCollapsed} onOpenChange={open => {
        setSidebarCollapsed(!open);
        try { localStorage.setItem('rag_sidebar_collapsed', String(!open)); } catch {}
      }} style={{'--sidebar-width':'14rem'} as React.CSSProperties} className="h-screen min-h-0 w-screen overflow-hidden bg-background text-foreground">
        <Toaster />
        {/* 登录/注册拦截弹窗 */}
        <AuthModal />

        {/* 左侧主菜单：智能问数、数据管理与系统管理 */}
        <Sidebar
          currentTab={currentTab}
          onTabChange={setCurrentTab}
        />

        {/* 右侧核心视图区 */}
        <div className="flex-1 flex flex-col h-full overflow-hidden bg-background">
          <Header
            currentTab={currentTab}
          />

          <div className="flex-1 flex overflow-hidden bg-background">
            {/* Tab 1: 智能问数 (主对话工作区) */}
            <div hidden={currentTab !== 'chat'} className={currentTab === 'chat' ? 'flex flex-1 min-w-0 overflow-hidden' : 'hidden'}>
                {/* 会话侧栏列表 (带 + New thread) */}
                <ThreadList
                  conversations={conversations.filter(conversation => conversation.workspace_id === workspaceId)}
                  activeId={activeSessionId}
                  onDelete={handleDeleteSession}
                  onRename={handleRenameSession}
                  onTogglePin={handleTogglePinSession}
                  workspaces={workspaces}
                  workspaceId={workspaceId}
                  onWorkspaceChange={handleSelectWorkspace}
                  onManageWorkspaces={() => setCurrentTab('workspaces')}
                  workspaceDisabled={!scopeReady}
                  isCollapsed={threadListCollapsed}
                  onToggleCollapse={toggleThreadList}
                />

                {/* 聊天对话主容器 */}
                <div className="flex-1 flex flex-col min-w-0 bg-background">
                <Thread
                  workspaceId={workspaceId} workspaceVersion={activeWorkspace?.version}
                  workspaceWarning={scopeReady ? workspaceWarning || (pendingQuestion ? '上次提问未完成，可以继续提问。' : '') : ''}
                  pendingQuestion={pendingQuestion}
                  workspaceActionLabel={pendingQuestion && !workspaceNeedsSetup ? '继续提问' : workspaceNeedsSetup ? '配置业务空间' : undefined}
                  onWorkspaceAction={handleWorkspaceNoticeAction}
                  sendDisabled={!scopeReady}
                  composerKey={activeSessionId ? `session:${activeSessionId}` : `draft:${draftSequence}`}
                  kbIds={selectedKbIds}
                  sourceIds={selectedSourceIds}
                  threadListCollapsed={threadListCollapsed}
                  onToggleThreadList={toggleThreadList}
                  selectedModel={selectedModel}
                  onModelChange={handleModelChange}
                />
                </div>
            </div>
            <div hidden={currentTab !== 'workspaces'} className={currentTab === 'workspaces' ? 'flex-1 overflow-y-auto bg-background' : 'hidden'}>
              <WorkspacesView key={user?.id || 'anonymous'} workspaces={workspaces} knowledgeBases={knowledgeBases} dataSources={dataSources}
                editRequest={editRequest} onSaved={updated => {workspaceEpoch.current += 1; setWorkspaces(items => items.some(w => w.id === updated.id) ? items.map(w => w.id === updated.id ? updated : w) : [...items,updated]); setScopeWarning('');}}
                onStart={startWorkspaceConversation} onReturn={() => setCurrentTab('chat')} onManage={setCurrentTab} />
            </div>

            {currentTab === 'feedback' && user?.role === 'feedback_admin' && <div className="flex-1 overflow-y-auto bg-background"><FeedbackView onForbidden={() => setCurrentTab('chat')} /></div>}
            {/* 系统管理 -> 应用配置 */}
            {currentTab === 'config' && (
              <div className="flex-1 overflow-y-auto bg-background">
                <AppConfigView />
              </div>
            )}

            {currentTab === 'data' && (
              <div className="flex-1 overflow-y-auto bg-background">
                <div className="px-6 pt-4"><Button variant="outline" onClick={() => setCurrentTab('workspaces')}>返回业务空间</Button></div>
                <DataSourcesView />
              </div>
            )}

            {/* 数据管理 -> 知识库（文档上传与分析进度） */}
            {currentTab === 'knowledge' && (
              <div className="flex-1 overflow-y-auto bg-background">
                <div className="px-6 pt-4"><Button variant="outline" onClick={() => setCurrentTab('workspaces')}>返回业务空间</Button></div>
                <KnowledgeView />
              </div>
            )}
          </div>
        </div>
      </SidebarProvider>
      </TooltipProvider>
      </RuntimeFeedbackProvider>
    </ChatRuntimeProvider>
  );
}

function RuntimeFeedbackProvider({sessionId,children}:{sessionId:string|null;children:React.ReactNode}) {
  const messages=useAuiState(s=>s.thread.messages);
  return <FeedbackProvider sessionId={sessionId} messages={messages.map(message=>fromRuntimeMessage(message,sessionId || ''))}>{children}</FeedbackProvider>;
}
