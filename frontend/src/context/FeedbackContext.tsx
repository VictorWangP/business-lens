import React, {createContext, useCallback, useContext, useEffect, useRef, useState} from 'react';
import {useAuth} from './AuthContext';
import {apiRequest} from '../services/api';
import type {FeedbackContextItem,FeedbackSummary} from '../types/feedback';

interface FeedbackState {
  records:Record<string,FeedbackSummary>; items:Record<string,FeedbackContextItem>; ready:boolean; error:string; refresh:()=>void;
  remember:(record:FeedbackSummary)=>void; questionFor:(id:string)=>string;
}
const Context = createContext<FeedbackState|null>(null);
export const useFeedback = () => useContext(Context);
export function FeedbackProvider({sessionId,children}:{sessionId:string|null;children:React.ReactNode}) {
  const {user} = useAuth();
  const scope = `${user?.id || ''}:${sessionId || ''}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const [state,setState] = useState<{scope:string; items:Record<string,FeedbackContextItem>; ready:boolean; error:string}>({scope:'',items:{},ready:false,error:''});
  const [reload,setReload] = useState(0);
  const refresh = useCallback(()=>setReload(value=>value+1),[]);
  useEffect(()=>{
    const controller = new AbortController();
    setState({scope, items:{},ready:!sessionId || !user,error:''});
    if (sessionId && user) apiRequest<{items:FeedbackContextItem[]}>(`/sessions/${sessionId}/feedback-context`,{signal:controller.signal}).then(response=>{
      if (controller.signal.aborted) return;
      const items=Object.fromEntries((Array.isArray(response?.items) ? response.items : []).map(item=>[item.message_id,item]));
      setState({scope,items,ready:true,error:''});
    }).catch(error=>{
      if (!controller.signal.aborted) setState({scope,items:{},ready:false,error:error.message});
    });
    return ()=>controller.abort();
  },[scope,reload]);
  useEffect(()=>{
    window.addEventListener('focus',refresh); window.addEventListener('feedback:updated',refresh);
    return ()=>{window.removeEventListener('focus',refresh);window.removeEventListener('feedback:updated',refresh);};
  },[refresh]);
  const remember = (record:FeedbackSummary)=>{
    if (currentScope.current !== scope) return;
    setState(previous=>{
      const items=previous.scope===scope ? previous.items : {};
      const existing=items[record.message_id];
      return {scope,ready:true,error:'',items:{...items,[record.message_id]:{
        message_id:record.message_id,run_id:existing?.run_id || null,run_status:existing?.run_status || 'completed',
        eligible:true,ineligible_reason:null,question_message_id:existing?.question_message_id || null,
        question_preview:existing?.question_preview || null,feedback:record,
      }}};
    });
  };
  const items=state.scope===scope ? state.items : {};
  const records=Object.fromEntries(Object.values(items).filter(item=>item.feedback).map(item=>[item.message_id,item.feedback!])) as Record<string,FeedbackSummary>;
  const questionFor=(id:string)=>items[id]?.question_preview || '原问题未能从服务端关联';
  return <Context.Provider value={{records,items,ready:state.scope===scope && state.ready,error:state.scope===scope ? state.error : '',refresh,remember,questionFor}}>{children}</Context.Provider>;
}
