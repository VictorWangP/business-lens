import React, {useState, useEffect} from 'react';
import type {Workspace} from '../components/workspaces/WorkspacesView';
import type {DataSource} from '../components/data/DataSourcesPanel';
import type {Conversation} from '../types/chat';
import {apiRequest} from '../services/api';
import {toast} from 'sonner';

// Session selection and workspace scope change together; keep their state in one place.
export function useChatSession(userId: string | undefined, currentTab: string,
  setCurrentTab: (tab: string) => void, availableLlmModels: {id:string}[], defaultModelId: string) {
  const [draftModel, setDraftModel] = useState('');
  // 对话与会话状态
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const preferredModel = activeSessionId
    ? conversations.find(session => session.id === activeSessionId)?.model : draftModel;
  const selectedModel = [preferredModel, defaultModelId, availableLlmModels[0]?.id]
    .find(id => id && availableLlmModels.some(model => model.id === id)) || '';

  const handleModelChange = (modelId: string) => {
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

  // 数据源与业务空间状态
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeWarning, setScopeWarning] = useState('');
  const [draftId, setDraftId] = useState(() => crypto.randomUUID());
  const [editRequest, setEditRequest] = useState<{id: string; sequence: number} | null>(null);
  const workspaceEpoch = React.useRef(0);
  const activeWorkspace = workspaces.find(w => w.id === workspaceId);
  const activeConversation = conversations.find(c => c.id === activeSessionId);
  const selectedSourceIds = activeWorkspace?.source_ids || [];
  const workspaceWarning = scopeWarning || (!workspaceId ? '请选择业务空间后提问。' : !activeWorkspace ? '绑定的业务空间不可用，请在可用空间新建对话。' :
    activeWorkspace.status === 'invalid' ? '当前空间存在不可用来源，请前往业务空间管理页检查配置。' :
    !selectedSourceIds.length ? '当前空间尚未关联数据源，请前往业务空间管理页配置。' :
    activeConversation?.scope_version && activeConversation.scope_version !== activeWorkspace.version ? '业务空间配置已更新，后续提问将使用最新来源。' : '');
  const workspaceNeedsSetup = !activeWorkspace || activeWorkspace.status === 'invalid' || !selectedSourceIds.length;

  useEffect(() => {
    let cancelled = false;
    workspaceEpoch.current += 1;
    setScopeReady(false);
    setConversations([]); setActiveSessionId(null);
    setDataSources([]); setWorkspaces([]); setWorkspaceId('');
     setScopeWarning(''); setEditRequest(null);
    setCurrentTab('chat'); setDraftId(crypto.randomUUID());
    if (userId) {
      Promise.all([
        apiRequest<Conversation[]>('/sessions'),
        apiRequest<DataSource[]>('/data-sources'),
        apiRequest<Workspace[]>('/workspaces'),
      ]).then(([sessions, sources, spaces]) => {
        if (cancelled) return;
        setConversations(sessions); setDataSources(sources); setWorkspaces(spaces);
        const first = sessions[0];
        let remembered = '';
        try { remembered = localStorage.getItem(`rag_workspace:${userId}`) || ''; } catch {}
        const fallback = spaces.find(w => w.id === remembered) || spaces.find(w => w.name === '默认业务空间') || spaces[0];
        setWorkspaceId(first ? first.workspace_id || '' : fallback?.id || '');
        setActiveSessionId(first?.id || null); setScopeReady(true);
      }).catch(error => { if (!cancelled) setScopeWarning('加载业务空间失败：' + error.message + '。请刷新重试。'); });
    }
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    if (!scopeReady || !userId || (currentTab !== 'chat' && currentTab !== 'workspaces')) return;
    let cancelled = false;
    const epoch = workspaceEpoch.current;
    Promise.all([apiRequest<Workspace[]>('/workspaces'), apiRequest<DataSource[]>('/data-sources')])
      .then(([spaces, sources]) => {
        if (cancelled || epoch !== workspaceEpoch.current) return;
        setWorkspaces(spaces); setDataSources(sources); setScopeWarning('');
      }).catch(error => { if (!cancelled) setScopeWarning('刷新业务空间失败：' + error.message); });
    return () => { cancelled = true; };
  }, [currentTab, scopeReady, userId]);

  useEffect(() => {
    if (!scopeReady || !userId || !workspaceId) return;
    try { localStorage.setItem(`rag_workspace:${userId}`, workspaceId); } catch {}
  }, [workspaceId, scopeReady, userId]);

  useEffect(() => {
    if (!scopeReady || !userId) return;
    let active = true;
    const controller = new AbortController();
    const refresh = () => { const epoch = workspaceEpoch.current; void apiRequest<Workspace[]>('/workspaces', {signal:controller.signal})
      .then(spaces => {if (active && epoch === workspaceEpoch.current) setWorkspaces(spaces);}).catch(() => {}); };
    const timer = window.setInterval(refresh, 10000);
    window.addEventListener('focus',refresh);
    return () => {active=false; controller.abort(); window.clearInterval(timer); window.removeEventListener('focus',refresh);};
  }, [scopeReady, userId]);

  const openWorkspaceConfig = () => {
    setEditRequest(current => ({id:workspaceId, sequence:(current?.sequence || 0) + 1}));
    setCurrentTab('workspaces');
  };
  const startWorkspaceConversation = (id:string) => {
    setActiveSessionId(null);setWorkspaceId(id);setScopeWarning('');
    setDraftId(crypto.randomUUID());setCurrentTab('chat');setDraftModel('');
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
         setScopeWarning(''); setDraftId(crypto.randomUUID());
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
    setActiveSessionId(id);setWorkspaceId(session.workspace_id || '');setScopeWarning('');
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
    onSwitchToNewThread:handleNewSession,onRename:handleRenameSession,onDelete:handleDeleteSession};
  const onSettled=(id:string)=>{
    if (!activeSessionId && id === draftId) setActiveSessionId(id);
    window.dispatchEvent(new Event('feedback:updated'));
    void apiRequest<Conversation[]>('/sessions').then(setConversations).catch(()=>{});
  };

  return {selectedModel, handleModelChange, conversations, activeSessionId, threadId:activeSessionId || draftId,
    dataSources, workspaces, workspaceId, scopeReady, scopeWarning, setScopeWarning,
    editRequest, workspaceEpoch, activeWorkspace, selectedSourceIds,
    workspaceWarning, workspaceNeedsSetup, threadList, onSettled, setWorkspaces,
    handleDeleteSession, handleRenameSession, handleTogglePinSession, handleSelectSession, handleSelectWorkspace,
    handleWorkspaceNoticeAction, startWorkspaceConversation};
}
