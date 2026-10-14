import React, {createContext, useContext, useMemo, useRef} from 'react';
import {AssistantRuntimeProvider, ExportedMessageRepository, type ThreadHistoryAdapter} from '@assistant-ui/react';
import {useAgUiRuntime} from '@assistant-ui/react-ag-ui';
import {HttpAgent} from '@ag-ui/client';
import type {RunAgentInput} from '@ag-ui/core';
import {apiRequest, getToken} from '../../services/api';
import {toRuntimeMessage} from '../../lib/chat-runtime';
import type {Message} from '../../types/chat';
import {toast} from 'sonner';

const CancelContext = createContext<() => void>(() => {});
export const useCancelPersistentRun = () => useContext(CancelContext);

class BusinessAgent extends HttpAgent {
  onRequest!: (runId:string)=>void;
  scope!: () => {workspace_id:string;model:string};
  protected requestInit(input: RunAgentInput): RequestInit {
    this.onRequest(input.runId);
    const latest=[...input.messages].reverse().find(message=>message.role==='user');
    const init = super.requestInit({...input, messages:latest ? [latest] : [], tools:[], context:[], state:{}, forwardedProps:this.scope()});
    return {...init, headers:{...init.headers, Authorization:`Bearer ${getToken() || ''}`}};
  }
}

export function ChatRuntimeProvider({sessionId, workspaceId, model, disabled, adapters, threadList, onSettled, children}: {
  sessionId:string|null;workspaceId:string;model:string;disabled:boolean;adapters:any;threadList:any;
  onSettled:(threadId:string)=>void;children:React.ReactNode;
}) {
  const scope=useRef({workspace_id:workspaceId,model});scope.current={workspace_id:workspaceId,model};
  const runId=useRef<string>();
  const settled=useRef(onSettled);settled.current=onSettled;
  const agent=useMemo(()=>{
    const agent=new BusinessAgent({url:'/api/chat/stream', threadId:sessionId || crypto.randomUUID(),
      fetch:async (url,init)=>{
        const response=await fetch(url,init);
        const id=response.headers.get('X-Run-Id');
        if(id)runId.current=id;
        return response;
      }});
    agent.scope=()=>scope.current;agent.onRequest=id=>{runId.current=id;};
    agent.subscribe({
      onRunFinishedEvent:()=>{settled.current(agent.threadId);},
    });
    return agent;
  },[]);
  const history=useMemo<ThreadHistoryAdapter>(()=>({
    async load() {
      if (!sessionId) return {messages:[]};
      const messages=await apiRequest<Message[]>(`/sessions/${sessionId}/messages`);
      const last=messages[messages.length-1];
      const resume=last?.role==='assistant' && ['queued','running','cancel_requested','paused'].includes(last.tool_calls?.status || '');
      if (resume) runId.current=last.tool_calls?.run_id;
      // Official runtime resumes through its normal agent path. The server recognizes
      // the persisted user-message ID and replays the existing run without re-execution.
      return {...ExportedMessageRepository.fromArray((resume ? messages.slice(0,-1) : messages).map(toRuntimeMessage)),
        unstable_resume:resume};
    },
    async append() {}, // The server owns the archive; the browser never writes it twice.
  }),[]);
  const runtime=useAgUiRuntime({agent, showThinking:false, isSendDisabled:disabled,
    onError:error=>toast.error(error.message), adapters:{...adapters, history, threadList}});
  const cancel=()=>{
    const id=runId.current;
    if (!id) return;
    void (async()=>{
      for(let attempt=0;attempt<10;attempt++){
        try {await apiRequest(`/runs/${id}/cancel`,{method:'POST'});return;}
        catch(error:any){if(error.status!==404 || attempt===9)throw error;}
        await new Promise(resolve=>setTimeout(resolve,200));
      }
    })().catch(error=>toast.error(error.message));
  };
  return <AssistantRuntimeProvider runtime={runtime}><CancelContext.Provider value={cancel}>{children}</CancelContext.Provider></AssistantRuntimeProvider>;
}
