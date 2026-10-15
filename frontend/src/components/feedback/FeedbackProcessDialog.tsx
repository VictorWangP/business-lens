import React, {useEffect,useRef,useState} from 'react';
import {toast} from 'sonner';
import {apiRequest} from '../../services/api';
import {FeedbackDetail,FeedbackStatus,statusLabels,reasonLabels,feedbackTime,errorMessage,errorStatus} from '../../types/feedback';
import {Dialog,DialogContent,DialogDescription,DialogFooter,DialogHeader,DialogTitle} from '../ui/dialog';
import {Button} from '../ui/button';
import {Label} from '../ui/label';
import {Textarea} from '../ui/textarea';
import {MarkdownContent} from '../chat/MarkdownContent';
import {BusinessAnswerContent} from '../chat/BusinessAnswerPart';
import {DiscardDialog,FeedbackSelect} from './FeedbackShared';

export function FeedbackProcessDialog({id,onClose,onSaved}:{id:string;onClose:()=>void;onSaved:()=>void}) {
  const [detail,setDetail]=useState<FeedbackDetail|null>(null),[status,setStatus]=useState<FeedbackStatus>('pending'),[note,setNote]=useState('');
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[discard,setDiscard]=useState(false);
  const [reload,setReload]=useState(0);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    apiRequest<FeedbackDetail>(`/feedback/${id}`,{signal:controller.signal}).then(value=>{
      if(controller.signal.aborted)return;
      setDetail(value);setStatus(value.status);setNote(value.processing_note);setConflict(false);
    }).catch(error=>{if(controller.signal.aborted)return;setError(errorMessage(error));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[id,reload]);
  const dirty=!!detail && (status!==detail.status || note!==detail.processing_note);
  const close=()=>{if(busy)return;if(dirty)setDiscard(true);else onClose();};
  const reloadConflict=async()=>{
    setBusy(true);
    try{
      const value=await apiRequest<FeedbackDetail>(`/feedback/${id}`);
      if(!alive.current)return;
      setDetail(value);setConflict(false);setError('最新记录已加载，当前草稿已保留。请对照最新备注核查后再确认。');
    }catch(error){if(alive.current)setError(errorMessage(error));}
    finally{if(alive.current)setBusy(false);}
  };
  const save=async()=>{
    if(!detail || busy || conflict)return;
    setBusy(true);setError('');
    try{
      await apiRequest<FeedbackDetail>(`/feedback/${id}`,{method:'PATCH',body:JSON.stringify({status,processing_note:note.trim(),expected_version:detail.version})});
      if(!alive.current)return;
      toast.success('反馈处理已保存');window.dispatchEvent(new Event('feedback:updated'));onSaved();
    }catch(error){
      if(!alive.current)return;
      if(errorStatus(error)===409){setConflict(true);setError('记录已被其他处理人更新，请重新加载后处理。当前草稿已保留。');}
      else if(!errorStatus(error)){
        // A lost HTTP response may still have committed. Reconcile without overwriting drafts.
        try{
          const latest=await apiRequest<FeedbackDetail>(`/feedback/${id}`);
          if(!alive.current)return;
          if(latest.status===status && latest.processing_note===note.trim()){
            toast.success('反馈处理已保存');window.dispatchEvent(new Event('feedback:updated'));onSaved();return;
          }
          setConflict(latest.version!==detail.version);setError(latest.version!==detail.version ? '记录已有更新，请重新加载后处理。当前草稿已保留。' : errorMessage(error));
        }catch{if(alive.current)setError('无法确认保存结果，请恢复连接后重新加载记录。');setConflict(true);}
      }else setError(errorMessage(error));
    }finally{if(alive.current)setBusy(false);}
  };
  const invalid = !dirty || (status==='resolved' && !note.trim()) || (!!detail && detail.status==='resolved' && status==='pending' && (!note.trim() || note.trim()===detail.processing_note));
  const evidence=detail?.evidence_snapshot;
  const handledEvents=detail?.history.filter(event=>event.action!=='created') || [];
  const lastActor=handledEvents[handledEvents.length-1];
  return <>
    <Dialog open onOpenChange={value=>{if(!value)close();}}><DialogContent className="w-[90vw] max-w-[1080px] max-h-[85dvh] flex flex-col" onPointerDownOutside={event=>event.preventDefault()}>
      <DialogHeader><DialogTitle>反馈处理</DialogTitle><DialogDescription>核查原始问答并登记处理结果。已处理表示核查已有结论，不代表答案已修复。</DialogDescription></DialogHeader>
      {loading ? <p role="status" className="p-6 text-muted-foreground">正在加载反馈…</p> : detail && evidence ? <div className="grid grid-cols-1 min-w-0 min-h-0 gap-6 overflow-y-auto pr-1 md:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)]">
        <div className="min-w-0 space-y-5">
          <section><h3 className="mb-2 text-sm font-semibold text-muted-foreground">用户提问</h3><p className="rounded-xl bg-muted p-4 whitespace-pre-wrap break-words">{detail.question}</p></section>
          <section><h3 className="mb-2 text-sm font-semibold text-muted-foreground">AI 回复</h3><div className="rounded-xl border border-amber-300/70 bg-amber-50/50 dark:bg-amber-950/20 p-4 overflow-x-auto">
            <MarkdownContent text={evidence.answer.content}/>
            <BusinessAnswerContent presentation={evidence.presentation}/>
          </div></section>
          <section className="text-sm space-y-2"><h3 className="font-semibold text-muted-foreground">用户反馈</h3><p>{reasonLabels[detail.reason]} · {detail.user.name} · {feedbackTime(detail.created_at)}</p><p className="whitespace-pre-wrap break-words">{detail.user_comment || '未填写补充说明'}</p>{detail.original_deleted && <p className="text-muted-foreground">原记录已删除，当前展示提交时的快照。</p>}</section>
          <details className="text-sm"><summary className="cursor-pointer font-medium">来源与上下文</summary><div className="mt-3 space-y-3">
            <p>模型：{evidence.execution.model || '无记录'} · 空间：{evidence.resource.workspace_name || '无记录'} · 资源版本：{evidence.resource.scope_version}</p>
            <p className="text-xs text-muted-foreground">以下内容为反馈时保存的证据，不会重新查询数据。</p>
            {evidence.context.public_history.length ? <details><summary className="cursor-pointer">关联上下文</summary>{evidence.context.public_history.map((entry,index)=><div key={index} className="mt-2 rounded-lg bg-muted p-3"><p className="text-xs text-muted-foreground">{entry.role==='user' ? '用户' : '助手'}</p><MarkdownContent text={entry.content}/></div>)}</details> : <p>上下文：无记录</p>}
            {evidence.context.truncated && <p className="text-amber-700 dark:text-amber-300">公开对话背景已截取，仅供核查参考。</p>}
            {!!evidence.context.clarifications?.length && <details><summary className="cursor-pointer">暂停后补充条件</summary>{evidence.context.clarifications.map((entry:any,index:number)=><pre key={index} className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-muted p-3 text-xs">{JSON.stringify(entry.response,null,2)}</pre>)}</details>}
            {evidence.presentation.queries.length ? evidence.presentation.queries.map((query:any,index:number)=><details key={index}><summary className="cursor-pointer">查询 {query.citation_id || query.query_id} · {query.source_name || '业务结果'}{query.truncated ? '（已截断）' : ''}</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 text-xs">{JSON.stringify(query,null,2)}</pre></details>) : <p>查询依据：无记录</p>}
            {evidence.completeness.warnings.map(warning=><p key={warning} className="text-amber-700 dark:text-amber-300">{warning}</p>)}
          </div></details>
        </div>
        <div className="space-y-5">
          <div className="space-y-2"><Label>处理状态</Label><FeedbackSelect label="处理状态" value={status} onChange={value=>setStatus(value as FeedbackStatus)} options={statusLabels} disabled={busy}/></div>
          <div className="space-y-2"><Label htmlFor="processing-note">处理备注{status==='resolved' || detail.status==='resolved' ? '（必填）' : ''}</Label><Textarea id="processing-note" value={note} onChange={event=>setNote(event.target.value)} maxLength={4000} rows={10} disabled={busy} placeholder="请填写核查结论、依据及后续动作…"/><p className="text-right text-xs text-muted-foreground">{note.length}/4000 · 仅处理人员可见</p></div>
          <div className="text-xs text-muted-foreground space-y-2"><p>最近处理人：{lastActor ? `${lastActor.actor_name}${lastActor.actor_id ? '' : '（已删除账号）'}` : '尚未处理'}</p><p>最近处理时间：{feedbackTime(detail.last_handled_at)}</p><p>版本：{detail.version}</p></div>
          <details className="text-sm"><summary className="cursor-pointer font-medium">处理历史（{detail.history.length}）</summary><ol className="mt-3 space-y-3">{detail.history.map(event=><li key={event.version} className="rounded-lg border p-3 space-y-1"><p>{event.actor_name}{!event.actor_id && '（已删除账号）'} · v{event.version}</p><p className="text-xs text-muted-foreground">{feedbackTime(event.created_at)}</p><p>{event.from_status ? `${statusLabels[event.from_status]} → ` : '创建 → '}{statusLabels[event.to_status]}</p>{event.old_note && <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">原备注：{event.old_note}</p>}{event.new_note && <p className="whitespace-pre-wrap break-words">{event.new_note}</p>}</li>)}</ol></details>
          {dirty && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">对照数据库当前备注</summary><p className="whitespace-pre-wrap break-words mt-2">{detail.processing_note || '暂无备注'}</p></details>}
        </div>
      </div> : null}
      {error && <div role="alert" className="text-sm text-destructive space-y-2"><p>{error}</p>{conflict ? <Button variant="outline" size="sm" onClick={reloadConflict} disabled={busy}>重新加载记录（保留草稿）</Button> : !detail && <Button variant="outline" size="sm" onClick={()=>setReload(value=>value+1)}>重试</Button>}</div>}
      <DialogFooter><Button variant="outline" disabled={busy} onClick={close}>取消</Button><Button onClick={save} disabled={!detail || loading || busy || conflict || invalid}>{busy ? '保存中…' : '确认'}</Button></DialogFooter>
    </DialogContent></Dialog>
    <DiscardDialog open={discard} onOpenChange={setDiscard} onDiscard={onClose}/>
  </>;
}
