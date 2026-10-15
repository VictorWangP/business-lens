import {BusinessAnswerPart} from './BusinessAnswerPart';
import { FeedbackButton } from '../feedback/FeedbackButton';
import React, { useState } from 'react';
import type { Message } from '../../types/chat';
import {
  Bot,
  User as UserIcon,
  Copy,
  Check,
  Volume2,
  Bookmark,
  Pencil,
  RotateCcw
} from 'lucide-react';
import { useConfig } from '../../context/ConfigContext';
import { useBookmarks } from '../../context/BookmarkContext';
import { apiRequest } from '../../services/api';
import { toast } from 'sonner';
import { AnalysisProcess } from './AnalysisProcess';
import { WorkingIndicator } from './WorkingIndicator';
import { MessagePrimitive, ActionBarPrimitive, ComposerPrimitive, ThreadPrimitive, useAui, useAuiState } from '@assistant-ui/react';
import { Button } from '../ui/button';
import { Avatar, AvatarFallback } from '../ui/avatar';
import { MarkdownText } from './MarkdownContent';
import { QueryCitationContext } from './QueryCitationContext';
import { QueryCitationBadge } from './QueryCitationBadge';
import type { QueryEvidence } from '../../types/chat';

interface MessageItemProps {
  message: Message;
  isWorking?: boolean;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message, isWorking = false }) => {
  const aui=useAui();
  const { configs } = useConfig();
  const { isBookmarked, toggleBookmark } = useBookmarks();
  const copied = useAuiState(s => s.message.isCopied);
  const isEditing = useAuiState(s => s.composer.isEditing);
  const isSpeaking = useAuiState(s => s.message.speech != null);
  const enableTTS = configs?.voice_tts?.is_enabled ?? false;

  const queries = React.useMemo<QueryEvidence[]>(() => {
    if (message.tool_calls?.presentation?.queries?.length) {
      return message.tool_calls.presentation.queries;
    }
    const events = message.tool_calls?.execution_events || [];
    const list: QueryEvidence[] = [];
    events.forEach(e => {
      if (e.result?.source_name || e.result?.sql) {
        list.push({
          query_id: e.tool_id || '',
          citation_id: (e.result as { citation_id?: string })?.citation_id || (e.tool_id ? `Q${e.tool_id}` : ''),
          source_name: e.result?.source_name || '业务数据',
          rows: [],
          truncated: Boolean(e.result?.truncated),
          sql: e.result?.sql,
        });
      }
    });
    return list;
  }, [message]);

  const uniqueQueries = React.useMemo(() => {
    const seen = new Set<string>();
    const list: QueryEvidence[] = [];
    for (const q of queries) {
      const key = q.source_name || q.citation_id || q.query_id;
      if (key && !seen.has(key)) {
        seen.add(key);
        list.push(q);
      }
    }
    return list;
  }, [queries]);

  const isUser = message.role === 'user';
  const bookmarked = isBookmarked(message.content);

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
          {!isUser && (
            <div className="flex items-center space-x-2 text-xs text-muted-foreground">
              <span className="font-semibold text-foreground">
                智能问数助手
              </span>
            </div>
          )}

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
                  <Button type="button" size="sm" variant="secondary" onClick={()=>{
                    const text=aui.message().composer().getState().text.trim();
                    if (!text) return;
                    aui.message().composer().cancel();
                    aui.thread().append({role:'user',content:[{type:'text',text}]});
                  }}>保存并发送</Button>
                </div>
              </ComposerPrimitive.Root>
            ) : isUser ? (
              <div className="whitespace-pre-wrap font-normal break-words">
                {message.content}
              </div>
            ) : (
              <>
                <AnalysisProcess message={message} isWorking={isWorking} />
                {isWorking && <WorkingIndicator message={message} />}
                <MessagePrimitive.Error><p role="alert" className="mt-2 text-destructive">执行未完成，请检查模型或数据配置后重试。</p></MessagePrimitive.Error>
                <QueryCitationContext.Provider value={queries}>
                  <MessagePrimitive.Parts components={{ Text: MarkdownText, data:{by_name:{"agui-activity/business-answer":BusinessAnswerPart},Fallback:()=>null}, tools:{Fallback:()=>null} }} />
                </QueryCitationContext.Provider>
                {!isWorking && uniqueQueries.length > 0 && (
                  <div className="mt-3.5 pt-2.5 border-t border-border/50 text-xs text-muted-foreground">
                    <span>数据来源：{uniqueQueries.map(q => q.source_name || '业务数据').filter(Boolean).join('、')}</span>
                  </div>
                )}
              </>
            )}
          </div>

          {/* 用户提问下方操作按钮（1. 收藏、2. 编辑、3. 重新发送、4. 复制） */}
          {isUser && !isEditing && (
            <div className="flex items-center justify-end space-x-1 pt-0.5">
              {/* 1. 收藏 */}
              <Button
                variant="ghost"
                size="icon"
                onClick={handleToggleBookmark}
                title={bookmarked ? '已收藏（点击取消）' : '收藏'}
                aria-label={bookmarked ? '已收藏' : '收藏'}
                className={`h-7 w-7 p-0 rounded-md transition flex items-center justify-center ${
                  bookmarked
                    ? 'text-amber-500 bg-amber-500/10 hover:bg-amber-500/20'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                }`}
              >
                <Bookmark className={`w-3.5 h-3.5 ${bookmarked ? 'fill-amber-400 text-amber-500' : ''}`} />
              </Button>

              {/* 2. 编辑 */}
              <ActionBarPrimitive.Edit asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  title="编辑问题"
                  aria-label="编辑问题"
                  className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition flex items-center justify-center"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </Button>
              </ActionBarPrimitive.Edit>

              {/* 3. 重新发送 */}
              <ThreadPrimitive.Suggestion prompt={message.content} send asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  title="重新发送"
                  aria-label="重新发送此提问"
                  className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-emerald-600 dark:hover:text-emerald-400 hover:bg-accent transition flex items-center justify-center"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </Button>
              </ThreadPrimitive.Suggestion>

              {/* 4. 复制 */}
              <ActionBarPrimitive.Copy asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  title={copied ? '已复制' : '复制'}
                  aria-label="复制问题内容"
                  className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition flex items-center justify-center"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                </Button>
              </ActionBarPrimitive.Copy>
            </div>
          )}

          {/* 助手消息底部操作工具栏 (复制、反馈、语音朗读 TTS) */}
          {!isUser && !isWorking && (
            <div className="flex items-center space-x-1 pt-0.5">
              <ActionBarPrimitive.Root>
                <ActionBarPrimitive.Copy asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="复制"
                    aria-label="复制回答"
                    className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition flex items-center justify-center"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </Button>
                </ActionBarPrimitive.Copy>
              </ActionBarPrimitive.Root>

              <FeedbackButton message={message} />

              {enableTTS && (isSpeaking ? (
                <ActionBarPrimitive.StopSpeaking asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="停止朗读"
                    aria-label="停止朗读"
                    className="h-7 w-7 p-0 rounded-md text-primary hover:bg-accent transition flex items-center justify-center"
                  >
                    <Volume2 className="w-3.5 h-3.5 animate-pulse" />
                  </Button>
                </ActionBarPrimitive.StopSpeaking>
              ) : (
                <ActionBarPrimitive.Speak asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="朗读"
                    aria-label="朗读回答"
                    className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition flex items-center justify-center"
                  >
                    <Volume2 className="w-3.5 h-3.5" />
                  </Button>
                </ActionBarPrimitive.Speak>
              ))}
            </div>
          )}
        </div>
      </div>
    </MessagePrimitive.Root>
  );
};
