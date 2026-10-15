import React, {useState} from 'react';
import {Flag} from 'lucide-react';
import {toast} from 'sonner';
import {Message} from '../../types/chat';
import {FeedbackReason,FeedbackSummary,reasonLabels,statusLabels,errorMessage} from '../../types/feedback';
import {useFeedback} from '../../context/FeedbackContext';
import {apiRequest} from '../../services/api';
import {Button} from '../ui/button';
import {Label} from '../ui/label';
import {Textarea} from '../ui/textarea';
import {Dialog,DialogContent,DialogDescription,DialogFooter,DialogHeader,DialogTitle} from '../ui/dialog';
import {MarkdownContent} from '../chat/MarkdownContent';
import {DiscardDialog,FeedbackSelect} from './FeedbackShared';

export function FeedbackButton({message}:{message:Message}) {
  const feedback=useFeedback();
  const [open,setOpen]=useState(false),[discard,setDiscard]=useState(false),[busy,setBusy]=useState(false);
  const [reason,setReason]=useState<FeedbackReason>('data_error'),[comment,setComment]=useState(''),[error,setError]=useState('');
  const record=feedback?.records[message.id];
  const eligibility=feedback?.items[message.id];
  if (!feedback || message.role!=='assistant' || !message.content.trim() ||
      (!eligibility && !feedback.error) || (eligibility && !eligibility.eligible && !record)) return null;
  const dirty=reason!=='data_error' || comment!=='';
  const close=()=>{if(busy)return;if(dirty)setDiscard(true);else setOpen(false);};
  const reset=()=>{setOpen(false);setDiscard(false);setReason('data_error');setComment('');setError('');};
  const submit=async()=>{
    if(busy)return;
    setBusy(true);setError('');
    try {
      const result=await apiRequest<FeedbackSummary>(`/messages/${message.id}/feedback`,{method:'POST',body:JSON.stringify({reason,comment:comment.trim()})});
      feedback.remember(result);reset();toast.success(result.deduplicated ? '此回复已提交反馈' : '反馈已提交');
    } catch(error){setError(errorMessage(error));} finally {setBusy(false);}
  };
  const label = record ? `已反馈 · ${statusLabels[record.status]}` : feedback.error ? '反馈状态加载失败 · 重试' : '反馈错误';
  const title = feedback.error || (record ? `已反馈 · ${statusLabels[record.status]}` : '反馈');

  return <>
    <Button
      variant="ghost"
      size="icon"
      disabled={!!record || (!feedback.ready && !feedback.error)}
      onClick={() => { if (feedback.error) { feedback.refresh(); return; } setOpen(true); }}
      title={title}
      aria-label={label}
      className={`h-7 w-7 p-0 rounded-md transition flex items-center justify-center ${
        record ? 'text-amber-500' : 'text-muted-foreground hover:text-foreground hover:bg-accent'
      }`}
    >
      <Flag className="h-3.5 w-3.5" />
    </Button>
    <Dialog open={open} onOpenChange={value=>{if(!value)close();}}><DialogContent className="w-[90vw] max-w-2xl max-h-[85dvh] flex flex-col" onPointerDownOutside={event=>event.preventDefault()}>
      <DialogHeader><DialogTitle>反馈错误</DialogTitle><DialogDescription>将提交本次问题、回复及相关来源快照给反馈处理人员。请勿填写密码或凭证。</DialogDescription></DialogHeader>
      <div className="space-y-4 overflow-y-auto min-h-0 pr-1">
        <div><Label>用户提问</Label><p className="mt-2 rounded-lg bg-muted p-3 text-sm whitespace-pre-wrap">{feedback.questionFor(message.id)}</p></div>
        <details><summary className="cursor-pointer text-sm text-muted-foreground">查看原回答</summary><div className="mt-2 rounded-lg border p-3"><MarkdownContent text={message.content}/></div></details>
        <div className="space-y-2"><Label>反馈原因</Label><FeedbackSelect label="反馈原因" value={reason} onChange={value=>setReason(value as FeedbackReason)} options={reasonLabels} disabled={busy}/></div>
        <div className="space-y-2"><Label htmlFor="feedback-comment">补充说明{reason==='other' ? '（必填）' : '（可选）'}</Label><Textarea id="feedback-comment" value={comment} onChange={event=>setComment(event.target.value)} maxLength={2000} rows={4} disabled={busy} placeholder="请描述有误的内容及核查线索…"/><p className="text-right text-xs text-muted-foreground">{comment.length}/2000</p></div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </div>
      <DialogFooter><Button variant="outline" onClick={close} disabled={busy}>取消</Button><Button onClick={submit} disabled={busy || (reason==='other' && !comment.trim())}>{busy ? '提交中…' : '提交反馈'}</Button></DialogFooter>
    </DialogContent></Dialog>
    <DiscardDialog open={discard} onOpenChange={setDiscard} onDiscard={reset}/>
  </>;
}
