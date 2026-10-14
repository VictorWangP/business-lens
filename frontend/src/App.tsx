import { WorkspacesView, type Workspace } from './components/workspaces/WorkspacesView';
import { FeedbackProvider } from './context/FeedbackContext';
import { FeedbackView } from './components/feedback/FeedbackView';
import React, { useState, useEffect, useMemo } from 'react';
import { AssistantRuntimeProvider, useExternalStoreRuntime } from '@assistant-ui/react';
import { ChartToolUI, MetricToolUI } from './components/chat/AssistantToolUI';
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
import { toRuntimeMessage } from './lib/chat-runtime';
import { Button } from './components/ui/button';
import { SidebarProvider } from './components/ui/sidebar';
import { Toaster } from './components/ui/sonner';
import { TooltipProvider } from './components/ui/tooltip';
import { useAuth } from './context/AuthContext';
import { Conversation, Message } from './types/chat';
import { KnowledgeBase } from './types/knowledge';
import { apiRequest, getToken } from './services/api';

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
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const lastMessage = messages[messages.length - 1];
  // The message is the single source for live and restored follow-up questions.
  const suggestions = !isLoading && lastMessage?.role === 'assistant' &&
    !['queued', 'running', 'cancel_requested', 'partial', 'failed', 'cancelled'].includes(lastMessage.tool_calls?.status || '')
    ? lastMessage.tool_calls?.answer?.suggestions ?? lastMessage.tool_calls?.suggestions ?? [] : [];

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
  const skipHistory = React.useRef<string | null>(null);
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

  // abort controller
  const abortControllerRef = React.useRef<AbortController | null>(null);
  const runSubscriptionsRef = React.useRef(new Map<string, AbortController>());
  const lastRunSequenceRef = React.useRef(new Map<string, number>());
  const runConversationRef = React.useRef(new Map<string, string>());
  const activeSessionRef = React.useRef(activeSessionId);
  const activeRequestRunRef = React.useRef<string | null>(null);
  const pendingStopRef = React.useRef(false);
  useEffect(() => { activeSessionRef.current = activeSessionId; }, [activeSessionId]);

  // 加载会话列表与知识库列表
  const fetchConversations = async () => {
    try {
      const data = await apiRequest<Conversation[]>('/sessions');
      setConversations(data);
    } catch (e) {
      console.error('获取会话失败', e);
    }
  };

  const applyRunEvent = (event: any, fallbackAssistantId?: string, fallbackUserId?: string) => {
    const runId = event.run_id;
    if (typeof event.sequence === 'number') {
      const last = lastRunSequenceRef.current.get(runId) || 0;
      if (event.sequence <= last) return;
      lastRunSequenceRef.current.set(runId, event.sequence);
    }
    if (event.type === 'run_started' && event.conversation_id) {
      const conversationId = event.conversation_id as string;
      runConversationRef.current.set(runId, conversationId);
      activeRequestRunRef.current = runId;
      if (activeSessionRef.current === null || activeSessionRef.current === conversationId) {
        if (activeSessionRef.current === null) {
          // Keep the optimistic messages when the first run assigns a new session ID.
          // Existing sessions must still load history when the user switches back to them.
          skipHistory.current = conversationId;
          activeSessionRef.current = conversationId;
          setActiveSessionId(conversationId);
          setWorkspaceId(event.workspace_id || '');
        }
      }
      setConversations(items => items.some(c => c.id === conversationId) ? items : [{
        id: conversationId, title: event.title || '新建对话', model: selectedModel, workspace_id: event.workspace_id || workspaceId,
        kb_ids: [], source_ids: [], scope_version: event.scope_version || activeWorkspace?.version || 0,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      }, ...items]);
      if (pendingStopRef.current) {
        pendingStopRef.current = false;
        void apiRequest(`/runs/${runId}/cancel`, {method:'POST'}).catch(error => toast.error(error.message || '停止任务失败'));
      }
    }
    setMessages(prev => prev.map(message => {
      const isFallbackAssistant = fallbackAssistantId && message.id === fallbackAssistantId;
      const isFallbackUser = fallbackUserId && message.id === fallbackUserId;
      const sameRun = message.role === 'assistant' && message.tool_calls?.run_id === runId;
      if (!isFallbackAssistant && !isFallbackUser && !sameRun) return message;
      if (isFallbackUser && event.type === 'run_started') return {
        ...message, id: event.user_message_id || message.id,
        conversation_id: event.conversation_id || message.conversation_id,
      };
      if (message.role !== 'assistant' && !isFallbackAssistant) return message;
      let next = { ...message, id: event.assistant_message_id || message.id,
        conversation_id: event.conversation_id || message.conversation_id,
        tool_calls: { ...message.tool_calls, run_id: runId } } as Message;
      const calls = { ...next.tool_calls };
      if (typeof event.sequence === 'number') calls.last_sequence = event.sequence;
      if (event.type === 'run_started') calls.status = event.status || 'queued';
      else if (event.type === 'status') calls.status = event.status;
      else if (event.type === 'tool_start' || event.type === 'tool_end') next.execution_events = [...(next.execution_events || []), {type:event.type, name:event.name}];
      else if (event.type === 'query_result') calls.query_results = [...(calls.query_results || []), event];
      else if (event.type === 'chunk') next.content += event.content || '';
      else if (event.type === 'answer') {
        next.content = event.content;
        calls.answer = event.answer;
        delete calls.suggestions;
      }
      else if (event.type === 'suggestions' && !calls.answer) calls.suggestions = event.items || [];
      else if (event.type === 'tool_call') { calls.metrics = event.metrics; calls.chart = event.chart; }
      else if (event.type === 'citations') next.citations = event.items;
      else if (event.type === 'error') next.content = `${next.content}${next.content ? '\n' : ''}${event.message || '执行失败'}`;
      else if (event.type === 'done') {
        calls.status = event.status || 'failed';
        if (!calls.answer && event.suggestions) calls.suggestions = event.suggestions;
        if (calls.status === 'cancelled' && !next.content) next.content = '执行已停止';
      }
      next.tool_calls = calls;
      return next;
    }));
    const runConversationId = event.conversation_id || runConversationRef.current.get(runId);
    if ((event.type === 'run_started' || event.type === 'status') &&
        (!runConversationId || activeSessionRef.current === runConversationId)) {
      setIsLoading(event.status !== 'cancelled');
    } else if (event.type === 'done' && activeSessionRef.current &&
        runConversationRef.current.get(runId) === activeSessionRef.current) {
      setIsLoading(false);
      void fetchConversations();
    }
  };

  const startRunSubscription = async (runId: string, afterSequence = 0) => {
    if (runSubscriptionsRef.current.has(runId)) return;
    const controller = new AbortController();
    runSubscriptionsRef.current.set(runId, controller);
    const parseStream = async (response: Response) => {
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (!controller.signal.aborted) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split('\n\n'); buffer = frames.pop() || '';
        for (const frame of frames) {
          if (!frame.startsWith('data: ')) continue;
          try { applyRunEvent(JSON.parse(frame.slice(6))); }
          catch (error) { console.error('解析运行事件失败', error); }
        }
      }
    };
    try {
      const response = await fetch(`/api/runs/${runId}/events?after_sequence=${afterSequence}`, {
        headers: getToken() ? {Authorization: `Bearer ${getToken()}`} : {}, signal: controller.signal,
      });
      await parseStream(response);
    } catch (error: any) {
      if (error.name !== 'AbortError') console.error('恢复 Agent 运行事件失败', error);
    } finally {
      if (runSubscriptionsRef.current.get(runId) === controller) runSubscriptionsRef.current.delete(runId);
    }
  };


  useEffect(() => {
    let cancelled = false;
    workspaceEpoch.current += 1;
    setScopeReady(false);
    setConversations([]); setActiveSessionId(null); setMessages([]);
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
      cancelled = true; abortControllerRef.current?.abort(); abortControllerRef.current = null;
      runSubscriptionsRef.current.forEach(controller => controller.abort()); runSubscriptionsRef.current.clear();
      setIsLoading(false);
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
  const startWorkspaceConversation = (id: string) => {
    abortControllerRef.current?.abort(); abortControllerRef.current = null;
    activeRequestRunRef.current = null;
    messages.forEach(m => {
      const runId = m.tool_calls?.run_id;
      if (runId) { runSubscriptionsRef.current.get(runId)?.abort(); runSubscriptionsRef.current.delete(runId); }
    });
    setIsLoading(false);
    setActiveSessionId(null); setWorkspaceId(id); setMessages([]);
    setPendingQuestion(''); setScopeWarning(''); setDraftSequence(n => n + 1); setCurrentTab('chat');
    setDraftModel('');
  };

  // 切换会话时加载历史消息
  useEffect(() => {
    const controller = new AbortController();
    if (activeSessionId && skipHistory.current === activeSessionId) {
      skipHistory.current = null;
      return () => controller.abort();
    }
    if (activeSessionId) {
      apiRequest<Message[]>(`/sessions/${activeSessionId}/messages`, { signal: controller.signal })
        .then((msgs) => {
          if (controller.signal.aborted) return;
          setMessages(msgs);
          const activeRuns = msgs.filter(m => m.role === 'assistant' && m.tool_calls?.run_id &&
            ['queued', 'running', 'cancel_requested'].includes(m.tool_calls.status || ''));
          setIsLoading(activeRuns.length > 0);
          activeRuns.forEach(m => {
            const runId = m.tool_calls!.run_id!;
            const sequence = Number(m.tool_calls?.last_sequence || 0);
            runConversationRef.current.set(runId, activeSessionId);
            lastRunSequenceRef.current.set(runId, sequence);
            void startRunSubscription(runId, sequence);
          });
        })
        .catch((e) => { if (!controller.signal.aborted) console.error('加载历史消息失败', e); });
    } else {
      setMessages([]);
    }
    return () => controller.abort();
  }, [activeSessionId]);

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

  // 发送消息与流式响应处理
  const handleSend = async (queryText: string, model: string) => {
    if (!queryText.trim() || isLoading || !scopeReady || abortControllerRef.current) return;
    setPendingQuestion('');
    if (!activeWorkspace || activeWorkspace.status === 'invalid' || (!selectedKbIds.length && !selectedSourceIds.length)) {
      setPendingQuestion(queryText);
      setScopeWarning(!activeWorkspace ? '请先选择可用业务空间。' : '请在业务空间管理页配置可用来源后，返回继续提问。');
      return;
    }

    // 乐观添加用户消息
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      conversation_id: activeSessionId || '',
      role: 'user',
      content: queryText,
      created_at: new Date().toISOString(),
    };

    // 占位助手消息
    const assistantMsgId = `assistant-${Date.now()}`;
    const assistantMsg: Message = {
      id: assistantMsgId,
      conversation_id: activeSessionId || '',
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;
    activeRequestRunRef.current = null;
    try {
      const token = getToken();
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({
          conversation_id: activeSessionId,
          workspace_id: workspaceId || null,
          query: queryText,
          model,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        throw new Error(typeof failure.detail === 'string' ? failure.detail : '请求失败，请检查模型配置');
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (reader) {
        const { done, value } = await reader.read();
        if (controller.signal.aborted) return;
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.replace('data: ', '').trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            applyRunEvent(data, assistantMsgId, userMsg.id);
            if (data.type === 'run_started' && activeSessionRef.current !== data.conversation_id) controller.abort();
            if (data.type === 'run_started') {
              const epoch = workspaceEpoch.current;
              void apiRequest<Workspace[]>('/workspaces').then(spaces => { if (epoch === workspaceEpoch.current) setWorkspaces(spaces); }).catch(() => {});
            }
            if (data.type === 'done' && ['partial','failed'].includes(data.status)) setPendingQuestion(queryText);
          } catch (e) {
            console.error('解析 SSE 帧失败', e);
          }
        }
      }
    } catch (err: any) {
      if (!controller.signal.aborted && err.name !== 'AbortError') {
        setPendingQuestion(queryText);
        console.error('对话生成错误', err);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: m.content || err.message || '请求异常，请稍后重试。', tool_calls: {...m.tool_calls, status: 'failed'} }
              : m
          )
        );
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        activeRequestRunRef.current = null;
        if (activeSessionRef.current === activeSessionId) setIsLoading(false);
      }
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    const active = [...messages].reverse().find(m => m.role === 'assistant');
    const runId = active?.tool_calls?.run_id;
    if (!runId) {
      pendingStopRef.current = true;
      if (active) {
        setMessages(items => items.map(m => m.id === active.id ? {...m, content: m.content || '执行已停止', tool_calls:{...m.tool_calls, status:'cancelled'}} : m));
        setIsLoading(false);
      }
      return;
    }
    setMessages(items => items.map(m => m.id === active.id ? {...m, tool_calls:{...m.tool_calls,status:'cancel_requested'}} : m));
    void apiRequest(`/runs/${runId}/cancel`, {method:'POST'}).then((result:any) => {
      if (result.status === 'cancelled') applyRunEvent({type:'done',run_id:runId,status:'cancelled'});
    }).catch(error => toast.error(error.message || '停止任务失败'));
  };

  const handleSelectSession = async (id: string) => {
    if (!scopeReady || id === activeSessionId) return;
    const activeRunIds = messages.map(m => m.tool_calls?.run_id).filter((runId): runId is string => Boolean(runId));
    activeRunIds.forEach(runId => { runSubscriptionsRef.current.get(runId)?.abort(); runSubscriptionsRef.current.delete(runId); });
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    activeRequestRunRef.current = null;
    setIsLoading(false);
    const session = conversations.find(c => c.id === id);
    if (!session) return;
    activeSessionRef.current = id;
    setActiveSessionId(id); setWorkspaceId(session.workspace_id || '');
    setMessages([]); setPendingQuestion(''); setScopeWarning('');
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

  const handleWorkspaceNoticeAction = () => {
    if (pendingQuestion && !workspaceNeedsSetup) {
      void handleSend(pendingQuestion, selectedModel);
      return;
    }
    openWorkspaceConfig();
  };

  const runtime = useExternalStoreRuntime<Message>({
    messages, isRunning: isLoading,
    suggestions: (configs?.next_questions?.is_enabled ?? true) ? suggestions.map(prompt => ({prompt})) : [],
    convertMessage: (message, index) => toRuntimeMessage(message, isLoading && index === messages.length - 1,
      messages[index - 1]?.role === 'user' ? messages[index - 1].content : ''),
    onNew: async message => {
      const text = message.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
      await handleSend(text, selectedModel);
    },
    // The backend stores a linear history: edits append a new question rather than rewrite past turns.
    onEdit: async message => {
      const text = message.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
      await handleSend(text, selectedModel);
    },
    onCancel: async () => handleStop(),
    adapters: {
      speech: configs?.voice_tts?.is_enabled ? audioAdapters.speech : undefined,
      dictation: configs?.voice_stt?.is_enabled ? audioAdapters.dictation : undefined,
      threadList: {
      threadId: activeSessionId || undefined,
      threads: conversations.filter(c => c.workspace_id === workspaceId).map(c => ({ id: c.id, status: 'regular' as const, title: c.title })),
      onSwitchToThread: handleSelectSession, onSwitchToNewThread: handleNewSession,
      onRename: handleRenameSession, onDelete: handleDeleteSession,
    } },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <FeedbackProvider key={user?.id || "anonymous"} sessionId={activeSessionId} messages={messages}>
      <TooltipProvider delayDuration={300}>
      <ChartToolUI />
      <MetricToolUI />
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
                  messages={messages}
                  isLoading={isLoading}
                  suggestions={suggestions}
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
      </FeedbackProvider>
    </AssistantRuntimeProvider>
  );
}
