import React, {createContext, useCallback, useContext, useEffect, useRef, useState} from 'react';
import {useAuth} from './AuthContext';
import {apiRequest} from '../services/api';
import type {FeedbackSummary} from '../types/feedback';
import type {Message} from '../types/chat';

interface FeedbackState {
  records:Record<string,FeedbackSummary>; ready:boolean; error:string; refresh:()=>void;
  remember:(record:FeedbackSummary)=>void; questionFor:(id:string)=>string;
}
const Context = createContext<FeedbackState|null>(null);
export const useFeedback = () => useContext(Context);
export function FeedbackProvider({sessionId,messages,children}:{sessionId:string|null;messages:Message[];children:React.ReactNode}) {
  const {user} = useAuth();
  const scope = `${user?.id || ''}:${sessionId || ''}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const [state,setState] = useState<{scope:string; records:Record<string,FeedbackSummary>; ready:boolean; error:string}>({scope:'',records:{},ready:false,error:''});
  const [reload,setReload] = useState(0);
  const refresh = useCallback(()=>setReload(value=>value+1),[]);
  useEffect(()=>{
    const controller = new AbortController();
    setState({scope, records:{},ready:!sessionId || !user,error:''});
    if (sessionId && user) apiRequest<FeedbackSummary[]>(`/sessions/${sessionId}/feedback`,{signal:controller.signal}).then(records=>{
      if (controller.signal.aborted) return;
      setState({scope, records:Object.fromEntries((Array.isArray(records) ? records : []).map(record=>[record.message_id,record])),ready:true,error:''});
    }).catch(error=>{
      if (!controller.signal.aborted) setState({scope,records:{},ready:false,error:error.message});
    });
    return ()=>controller.abort();
  },[scope,reload]);
  useEffect(()=>{
    window.addEventListener('focus',refresh); window.addEventListener('feedback:updated',refresh);
    return ()=>{window.removeEventListener('focus',refresh);window.removeEventListener('feedback:updated',refresh);};
  },[refresh]);
  const remember = (record:FeedbackSummary)=>{
    if (currentScope.current !== scope) return;
    setState(previous=>({scope,ready:true,error:'',records:{...(previous.scope===scope ? previous.records : {}),[record.message_id]:record}}));
  };
  const questionFor = (id:string)=>{
    const index=messages.findIndex(message=>message.id===id);
    return messages.slice(0,index).reverse().find(message=>message.role==='user')?.content || '原问题将由服务端关联';
  };
  return <Context.Provider value={{records:state.scope===scope ? state.records : {},ready:state.scope===scope && state.ready,error:state.scope===scope ? state.error : '',refresh,remember,questionFor}}>{children}</Context.Provider>;
}
