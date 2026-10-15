import { WorkspacesView } from './components/workspaces/WorkspacesView';
import { FeedbackProvider } from './context/FeedbackContext';
import { FeedbackView } from './components/feedback/FeedbackView';
import React, { useState, useEffect, useMemo } from 'react';
import {ChatRuntimeProvider} from './components/chat/ChatRuntimeProvider';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { ThreadList } from './components/chat/ThreadList';
import { Thread } from './components/chat/Thread';
import { AppConfigView } from './components/settings/AppConfigView';
import { DataSourcesView } from './components/data/DataSourcesView';
import { AuthModal } from './components/auth/AuthModal';
import { useConfig } from './context/ConfigContext';
import { createAudioAdapters } from './lib/audio-adapters';
import { toast } from 'sonner';
import { Button } from './components/ui/button';
import { SidebarProvider } from './components/ui/sidebar';
import { Toaster } from './components/ui/sonner';
import { TooltipProvider } from './components/ui/tooltip';
import { useAuth } from './context/AuthContext';
import {useChatSession} from './hooks/useChatSession';

export function AppContent() {
  const { user } = useAuth();
  const { configs } = useConfig();

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

  const {selectedModel, handleModelChange, conversations, activeSessionId, threadId,
    dataSources, workspaces, workspaceId, scopeReady, setScopeWarning,
    editRequest, workspaceEpoch, activeWorkspace, selectedSourceIds,
    workspaceWarning, workspaceNeedsSetup, threadList, onSettled, setWorkspaces,
    handleDeleteSession, handleRenameSession, handleTogglePinSession, handleSelectSession, handleSelectWorkspace,
    handleWorkspaceNoticeAction, startWorkspaceConversation} = useChatSession(
      user?.id, currentTab, setCurrentTab, availableLlmModels, defaultModelId);

  useEffect(() => () => audioAdapters.dispose(), [audioAdapters, currentTab, activeSessionId, user?.id,
    configs?.voice_stt?.is_enabled, configs?.voice_tts?.is_enabled]);

  return (
    <ChatRuntimeProvider key={user?.id || 'anonymous'} threadId={threadId}
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
                  onSelect={handleSelectSession}
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
                  workspaceWarning={scopeReady ? workspaceWarning : ''}
                  workspaceActionLabel={workspaceNeedsSetup ? '配置业务空间' : undefined}
                  onWorkspaceAction={handleWorkspaceNoticeAction}
                  sendDisabled={!scopeReady}
                  composerKey={threadId}
                  sourceIds={selectedSourceIds}
                  threadListCollapsed={threadListCollapsed}
                  onToggleThreadList={toggleThreadList}
                  selectedModel={selectedModel}
                  onModelChange={handleModelChange}
                />
                </div>
            </div>
            <div hidden={currentTab !== 'workspaces'} className={currentTab === 'workspaces' ? 'flex-1 overflow-y-auto bg-background' : 'hidden'}>
              <WorkspacesView key={user?.id || 'anonymous'} workspaces={workspaces} dataSources={dataSources}
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
          </div>
        </div>
      </SidebarProvider>
      </TooltipProvider>
      </RuntimeFeedbackProvider>
    </ChatRuntimeProvider>
  );
}

function RuntimeFeedbackProvider({sessionId,children}:{sessionId:string|null;children:React.ReactNode}) {
  return <FeedbackProvider sessionId={sessionId}>{children}</FeedbackProvider>;
}
