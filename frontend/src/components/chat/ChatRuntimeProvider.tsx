import React, {createContext, useContext, useEffect, useMemo, useRef, useState} from 'react';
import {AssistantRuntimeProvider, ExportedMessageRepository, type ThreadHistoryAdapter} from '@assistant-ui/react';
import {useAgUiRuntime, type UseAgUiRuntimeAdapters, type UseAgUiThreadListAdapter} from '@assistant-ui/react-ag-ui';
import {HttpAgent} from '@ag-ui/client';
import type {RunAgentInput} from '@ag-ui/core';
import {apiRequest, getToken} from '../../services/api';
import {toRuntimeMessage} from '../../lib/chat-runtime';
import type {Message} from '../../types/chat';
import {RunTimingContext} from './RunTimingContext';
import {toast} from 'sonner';

const CancelContext = createContext<() => Promise<void>>(async () => {});
export const useCancelPersistentRun = () => useContext(CancelContext);
type SessionList = Omit<UseAgUiThreadListAdapter, 'onSwitchToThread'>;

class BusinessAgent extends HttpAgent {
  scope!: () => {workspace_id:string; model:string};
  protected requestInit(input: RunAgentInput): RequestInit {
    const latest = [...input.messages].reverse().find(message => message.role === 'user');
    const init = super.requestInit({...input, messages:latest ? [latest] : [], tools:[], context:[], state:{}, forwardedProps:this.scope()});
    return {...init, headers:{...init.headers, Authorization:`Bearer ${getToken() || ''}`}};
  }
}

export function ChatRuntimeProvider({threadId, sessionId, workspaceId, model, disabled, adapters, threadList, onSettled, children}: {
  threadId:string; sessionId:string|null; workspaceId:string; model:string; disabled:boolean;
  adapters:Pick<UseAgUiRuntimeAdapters, 'speech' | 'dictation'>; threadList:SessionList;
  onSettled:(threadId:string)=>void; children:React.ReactNode;
}) {
  const latest = useRef({sessionId, workspaceId, model, onSettled, threadList});
  latest.current = {sessionId, workspaceId, model, onSettled, threadList};
  const run = useRef<{id:string; ready?:Promise<Response>}>();
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [runtimeThreadId, setRuntimeThreadId] = useState(threadId);
  const resume = useRef<{threadId:string; parentId:string} | null>(null);
  const agent = useMemo(() => {
    const instance = new BusinessAgent({url:'/api/chat/stream', threadId,
      fetch:(url, init) => {
        const input = JSON.parse(init?.body as string) as RunAgentInput;
        const current = {id:input.runId, ready:fetch(url, init)};
        run.current = current;
        // Cancellation waits for creation to commit before calling /cancel.
        return current.ready.then(response => {
          current.id = response.headers.get('X-Run-Id') || current.id;
          return response;
        });
      }});
    instance.scope = () => ({workspace_id:latest.current.workspaceId, model:latest.current.model});
    instance.subscribe({
      onRunFinishedEvent:event => {setStartedAt(null); latest.current.onSettled((event as any).threadId || agent.threadId);},
      onRunErrorEvent:() => {setStartedAt(null);},
    });
    return instance;
  }, []);

  const loadThread = async (id:string) => {
    const messages = id === latest.current.sessionId || latest.current.threadList.threads?.some(thread => thread.id === id)
      ? await apiRequest<Message[]>(`/sessions/${id}/messages`) : [];
    const last = messages[messages.length - 1];
    const isPaused = last?.role === 'assistant' && last.tool_calls?.status === 'paused' && Boolean(last.tool_calls?.interrupts?.length);
    const inFlight = last?.role === 'assistant' && ['queued','running','cancel_requested'].includes(last.tool_calls?.status || '');
    if (agent.threadId === id) {
      setStartedAt(inFlight ? last.created_at : null);
      run.current = (inFlight || isPaused) && last.tool_calls?.run_id ? {id:last.tool_calls.run_id} : undefined;
      agent.pendingInterrupts = isPaused ? ((last.tool_calls?.interrupts as any) || []) : [];
    }
    return {...ExportedMessageRepository.fromArray((inFlight ? messages.slice(0,-1) : messages).map(toRuntimeMessage)),
      unstable_resume:inFlight};
  };
  const load = useRef(loadThread); load.current = loadThread;
  const history = useMemo<ThreadHistoryAdapter>(() => ({
    load:() => load.current(agent.threadId),
    async append() {}, // The server owns the archive.
  }), [agent]);
  const runtime = useAgUiRuntime({agent, showThinking:false, isSendDisabled:disabled || switching,
    onError:error => toast.error(error.message), adapters:{...adapters, history, threadList:{
      ...threadList, threadId:runtimeThreadId,
      onSwitchToThread:async id => {
        agent.threadId = id;
        setRuntimeThreadId(id);
        const archive = await load.current(id);
        resume.current = archive.unstable_resume
          ? {threadId:id, parentId:archive.messages[archive.messages.length - 1]!.message.id} : null;
        return {messages:archive.messages.map(item => item.message)};
      },
    }}});

  // UI selection changes use the native switch path. Promoting a draft keeps the
  // same thread ID and never reloads or recreates the runtime.
  useEffect(() => {
    if (agent.threadId === threadId) return;
    let active = true;
    setSwitching(true);
    void runtime.threads.switchToThread(threadId)
      .then(() => {
        const pending = resume.current;
        if (active && agent.threadId === threadId && pending?.threadId === threadId) {
          resume.current = null;
          // The backend recognizes the archived user-message ID and replays
          // its existing run; the native runtime owns all event aggregation.
          runtime.thread.resumeRun({parentId:pending.parentId});
        }
      })
      .catch(error => {if (active) toast.error(error.message);})
      .finally(() => {if (active) setSwitching(false);});
    return () => {active = false;};
  }, [threadId, agent, runtime]);

  const cancel = async () => {
    const current = run.current;
    const currentThread = agent.threadId;
    if (!current) return;
    try {
      await current.ready;
      await apiRequest(`/runs/${current.id}/cancel`, {method:'POST'});
      if (agent.threadId === currentThread) runtime.thread.cancelRun();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '停止任务失败');
    }
  };
  return <AssistantRuntimeProvider runtime={runtime}><CancelContext.Provider value={cancel}>
    <RunTimingContext.Provider value={startedAt}>{children}</RunTimingContext.Provider>
  </CancelContext.Provider></AssistantRuntimeProvider>;
}
