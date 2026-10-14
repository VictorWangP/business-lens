import { FeedbackButton } from '../feedback/FeedbackButton';
import React, { useState } from 'react';
import {
  Bot,
  User as UserIcon,
  Copy,
  Check,
  Volume2,
  FileText,
  Bookmark,
  Pencil,
  RotateCcw
} from 'lucide-react';
import { Message, CitationItem } from '../../types/chat';
import { useConfig } from '../../context/ConfigContext';
import { useBookmarks } from '../../context/BookmarkContext';
import { apiRequest, downloadDocument } from '../../services/api';
import { toast } from 'sonner';
import { WorkingIndicator } from './WorkingIndicator';
import { MessagePrimitive, ActionBarPrimitive, ComposerPrimitive, ThreadPrimitive, useAuiState } from '@assistant-ui/react';
import { Button } from '../ui/button';
import { Avatar, AvatarFallback } from '../ui/avatar';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { MarkdownText } from './MarkdownContent';

const analysisActionLabels: Record<string, string> = {
  search_knowledge: '检索知识库', read_document_section: '读取文档内容',
  get_business_schema: '读取业务字段', query_metrics: '查询业务指标',
  execute_readonly_sql: '查询业务数据', list_available_resources: '确认可用资源',
};
const runStatusLabels: Record<string, string> = {
  queued: '排队中', running: '运行中', cancel_requested: '正在停止', completed: '完成',
  partial: '部分完成', failed: '执行失败', cancelled: '已停止',
};

interface MessageItemProps {
  message: Message;
  isWorking?: boolean;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message, isWorking = false }) => {
  const { configs } = useConfig();
  const { isBookmarked, toggleBookmark } = useBookmarks();
  const copied = useAuiState(s => s.message.isCopied);
  const isEditing = useAuiState(s => s.composer.isEditing);
  const isSpeaking = useAuiState(s => s.message.speech != null);
  const enableTTS = configs?.voice_tts?.is_enabled ?? false;
  const [activeCitation, setActiveCitation] = useState<CitationItem | null>(null);
  const [runDetails, setRunDetails] = useState<any>(null);

  const isUser = message.role === 'user';
  const bookmarked = isBookmarked(message.content);
  const executionEvents = message.execution_events || [];
  const runStatus = message.tool_calls?.status || '';

  const handleToggleBookmark = async () => {
    await toggleBookmark(message.content);
  };

  return (
    <MessagePrimitive.Root className={`flex w-full py-4 ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex max-w-3xl space-x-3.5 ${isUser ? 'flex-row-reverse space-x-reverse' : 'flex-row'}`}>
        {/* 头像 */}
        <Avatar className="h-8 w-8 rounded-xl"><AvatarFallback className="rounded-xl bg-primary text-primary-foreground">{isUser ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}</AvatarFallback></Avatar>

        {/* 消息主体 */}
        <div className="flex-1 min-w-0 space-y-2">
          {/* 角色与时间 */}
          <div className="flex items-center space-x-2 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">
              {isUser ? '我' : '智能问数助手'}
            </span>
          </div>

          {/* 消息框 */}
          <div
            className={`p-4 rounded-2xl text-sm leading-relaxed ${
              isUser
                ? 'bg-blue-600 text-white rounded-tr-sm shadow-sm'
                : 'bg-card border border-border text-card-foreground rounded-tl-sm shadow-sm'
            }`}
          >
            {/* 消息文本或内联编辑模式 */}
            {isUser && isEditing ? (
              <ComposerPrimitive.Root className="space-y-2.5">
                <ComposerPrimitive.Input aria-label="编辑问题内容" autoFocus rows={3} submitMode="enter" className="w-full p-2.5 rounded-xl border bg-background text-foreground text-sm resize-y" />
                <p className="text-xs text-white/80">修改后作为新问题发送，保留原有对话。</p>
                <div className="flex justify-end gap-2">
                  <ComposerPrimitive.Cancel asChild><Button type="button" variant="secondary" size="sm">取消</Button></ComposerPrimitive.Cancel>
                  <ComposerPrimitive.Send asChild><Button size="sm" variant="secondary">保存并发送</Button></ComposerPrimitive.Send>
                </div>
              </ComposerPrimitive.Root>
            ) : isUser ? (
              <div className="whitespace-pre-wrap font-normal break-words">
                {message.content}
              </div>
            ) : (
              <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
            )}

            {!isUser && isWorking && <WorkingIndicator message={message} />}
            {!isUser && !isWorking && (executionEvents.length > 0 || message.tool_calls?.run_id || message.tool_calls?.query_results?.length || runStatus) && (
              <details className="mt-2 text-xs text-muted-foreground">
                <summary className="w-fit cursor-pointer select-none hover:text-foreground">
                  分析过程
                  {runStatus in runStatusLabels ? ` · ${runStatusLabels[runStatus]}` : ''}
                </summary>
                {executionEvents.length > 0 && <ol className="mt-2 space-y-1 pl-4">
                  {executionEvents.map((event, index) => (
                    <li key={index}>{event.type === 'tool_start' ? '开始执行' : '执行结束'} · {analysisActionLabels[event.name || ''] || event.name}</li>
                  ))}
                </ol>}
                {runStatus && <p className="mt-2">执行状态：{runStatusLabels[runStatus] || runStatus}</p>}
                {message.tool_calls?.run_id && <details className="mt-2" onToggle={event => {
                  if (event.currentTarget.open && !runDetails) {
                    apiRequest(`/runs/${message.tool_calls?.run_id}`).then(setRunDetails).catch(error => setRunDetails({error: error.message}));
                  }
                }}>
                  <summary className="cursor-pointer text-primary">查看执行记录</summary>
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{runDetails ? JSON.stringify(runDetails, null, 2) : '正在加载…'}</pre>
                </details>}
                {message.tool_calls?.query_results?.map(query => <details key={query.query_id} className="mt-3">
                  <summary className="cursor-pointer text-primary">查询 {query.citation_id || query.query_id.slice(0, 8)} · {query.source_name} · {query.rows.length} 行{query.truncated ? '（已截断）' : ''}</summary>
                  <p className="mt-2">查询时间：{query.retrieved_at}</p>
                  <pre className="mt-1 overflow-auto whitespace-pre-wrap">{query.sql}</pre>
                  {query.parameters && Object.keys(query.parameters).length > 0 && <pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(query.parameters, null, 2)}</pre>}
                  <pre className="max-h-60 overflow-auto">{JSON.stringify(query.rows, null, 2)}</pre>
                </details>)}
              </details>
            )}
            {/* 知识库引用来源卡片 */}
            {message.citations && message.citations.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <div className="text-xs font-semibold text-muted-foreground mb-2 flex items-center space-x-1">
                  <FileText className="w-3.5 h-3.5 text-primary" />
                  <span>知识库溯源引用 ({message.citations.length} 处)</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {message.citations.map((cite, idx) => (
                    <Button variant="ghost"
                      key={idx}
                      onClick={() => setActiveCitation(cite)}
                      className="px-2.5 py-1 rounded-lg border border-border bg-muted/50 text-xs text-muted-foreground hover:border-primary hover:text-foreground transition flex items-center space-x-1"
                    >
                      <span className="text-blue-500 font-bold">[{cite.id}]</span>
                      <span className="truncate max-w-[140px]">{cite.doc_name}</span>
                    </Button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 用户提问下方操作按钮（1. 收藏、2. 编辑、3. 重新发送、4. 复制） */}
          {isUser && !isEditing && (
            <div className="flex items-center justify-end space-x-1 pt-0.5">
              {/* 1. 收藏 */}
              <Button variant="ghost"
                onClick={handleToggleBookmark}
                title={bookmarked ? '已收藏（点击取消）' : '收藏提问'}
                className={`px-2 py-1 rounded-md transition flex items-center space-x-1 text-xs ${
                  bookmarked
                    ? 'text-amber-500 bg-amber-500/10 hover:bg-amber-500/20'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                }`}
              >
                <Bookmark className={`w-3.5 h-3.5 ${bookmarked ? 'fill-amber-400 text-amber-500' : ''}`} />
                <span className="text-[11px] font-medium">{bookmarked ? '已收藏' : '收藏'}</span>
              </Button>

              <ActionBarPrimitive.Edit asChild><Button variant="ghost" size="sm" title="编辑问题"><Pencil className="w-3.5 h-3.5" /><span>编辑</span></Button></ActionBarPrimitive.Edit>

              {/* 3. 重新发送 */}
              <ThreadPrimitive.Suggestion prompt={message.content} send asChild><Button variant="ghost"
                title="重新发送此提问"
                className="px-2 py-1 rounded-md text-muted-foreground hover:text-emerald-600 dark:hover:text-emerald-400 hover:bg-accent transition flex items-center space-x-1 text-xs"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span className="text-[11px] font-medium">重新发送</span>
              </Button>

              </ThreadPrimitive.Suggestion>
              {/* 4. 复制 */}
              <ActionBarPrimitive.Copy asChild><Button variant="ghost"
                title="复制问题内容"
                className="px-2 py-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition flex items-center space-x-1 text-xs"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                <span className="text-[11px] font-medium">{copied ? '已复制' : '复制'}</span>
              </Button>
              </ActionBarPrimitive.Copy>
            </div>
          )}

          {/* 助手消息底部操作工具栏 (复制、语音朗读 TTS) */}
          {!isUser && !isWorking && (
            <div className="flex items-center space-x-1 pt-0.5">
              <ActionBarPrimitive.Root><ActionBarPrimitive.Copy asChild>
                <Button variant="ghost" size="icon" aria-label="复制回答"><Copy /></Button>
              </ActionBarPrimitive.Copy></ActionBarPrimitive.Root>

              <FeedbackButton message={message} />

              {enableTTS && (isSpeaking
                ? <ActionBarPrimitive.StopSpeaking asChild><Button variant="ghost" size="sm" aria-label="停止朗读"><Volume2 />停止朗读</Button></ActionBarPrimitive.StopSpeaking>
                : <ActionBarPrimitive.Speak asChild><Button variant="ghost" size="sm" aria-label="朗读回答"><Volume2 />朗读</Button></ActionBarPrimitive.Speak>)}
            </div>
          )}
        </div>
      </div>


      {/* 引用来源详情弹窗抽屉 */}
      <Dialog open={!!activeCitation} onOpenChange={open => { if (!open) setActiveCitation(null); }}>
        <DialogContent className="max-w-2xl max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>{activeCitation?.doc_name}</DialogTitle>
            <DialogDescription>来源 {activeCitation?.id} · 切片 {activeCitation?.chunk_index}
              {activeCitation?.pages?.length ? ` · 第 ${activeCitation.pages.join('、')} 页` : ''}
              {activeCitation?.version ? ` · 版本 ${activeCitation.version.slice(0,8)}` : ''}</DialogDescription></DialogHeader>
          {activeCitation?.retrieval_warning && <p className="text-sm text-amber-700 dark:text-amber-400">{activeCitation.retrieval_warning}</p>}
          <div className="whitespace-pre-wrap text-sm leading-relaxed">{activeCitation?.headings?.join(' / ')}{activeCitation?.headings?.length ? '\n\n' : ''}{activeCitation?.content}</div>
          <DialogFooter><Button variant="outline" onClick={async () => {
            if (!activeCitation) return;
            try { await downloadDocument(activeCitation.doc_id, activeCitation.doc_name); }
            catch (e) { toast.error(e instanceof Error ? e.message : '下载失败'); }
          }}>下载原件</Button><Button onClick={() => setActiveCitation(null)}>关闭</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </MessagePrimitive.Root>
  );
};
