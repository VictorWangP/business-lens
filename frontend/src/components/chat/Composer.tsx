import {useCancelPersistentRun} from './ChatRuntimeProvider';
import React, { useState, useEffect } from 'react';
import { ComposerPrimitive, useAui, useAuiState } from '@assistant-ui/react';
import { ArrowUp, Mic, Square, Trash2, Zap, X, Bot } from 'lucide-react';
import { useFrequentQuestions } from '../../hooks/useFrequentQuestions';
import { useConfig } from '../../context/ConfigContext';
import { useBookmarks } from '../../context/BookmarkContext';
import { Button } from '../ui/button';
import { Popover, PopoverTrigger, PopoverContent, PopoverClose } from '../ui/popover';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';

interface ComposerProps {
  sourceIds?: string[];
  workspaceId?: string;
  workspaceVersion?: number;
  composerKey?: string;
  sendDisabled?: boolean;
  isLoading: boolean;
  selectedModel?: string;
  onModelChange?: (model: string) => void;
}

export const Composer: React.FC<ComposerProps> = ({
  workspaceId, workspaceVersion, composerKey, isLoading, sendDisabled = false,
  sourceIds = [], selectedModel, onModelChange,
}) => {
  const { configs } = useConfig();
  const { bookmarks, removeBookmark } = useBookmarks();
  const cancelPersistentRun=useCancelPersistentRun();
  const composer = useAui().composer();
  useEffect(() => { composer.setText(''); }, [composerKey]);
  const isRecording = useAuiState(s => s.composer.dictation != null);
  const [quickOpen, setQuickOpen] = useState(false);
  const frequent = useFrequentQuestions(sourceIds, configs?.frequent_questions?.is_enabled ?? false, configs?.frequent_questions?.threshold ?? 3, isLoading, workspaceId, workspaceVersion);

  const availableModels = configs?.model_setting?.available_models.filter(m => m.type !== 'embedding') || [];
  const defaultModelId = configs?.model_setting?.default_model || '';
  const activeModelId = selectedModel || defaultModelId || availableModels[0]?.id || '';
  const currentModel = availableModels.find(m => m.id === activeModelId);

  function quickAsk(text: string) {
    if (isLoading || sendDisabled) return;
    composer.setText(text); composer.send(); setQuickOpen(false);
  }

  return <div className="w-full max-w-4xl mx-auto px-4 pb-5">
    <ComposerPrimitive.Root className="rounded-2xl border bg-background p-3 shadow-sm focus-within:ring-2 focus-within:ring-ring/20">
      <ComposerPrimitive.Input aria-label="输入问题" placeholder="询问业务数据、指标或报表…"
        rows={2} maxRows={8} submitMode="enter" disabled={isLoading || sendDisabled} addAttachmentOnPaste={false}
        className="w-full resize-none bg-transparent px-2 py-1 text-sm leading-6 outline-none placeholder:text-muted-foreground" />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {availableModels.length > 0 && onModelChange && activeModelId && (
            <Select
              value={activeModelId}
              onValueChange={onModelChange}
              disabled={isLoading || sendDisabled}
            >
              <SelectTrigger
                aria-label="切换模型"
                title={`当前模型：${currentModel?.name || activeModelId || '默认模型'}`}
                className="h-8 gap-1.5 border border-border/60 bg-muted/30 hover:bg-muted/60 text-xs font-medium px-2.5 rounded-lg shadow-none focus:ring-1 focus:ring-ring transition-colors max-w-[200px] w-auto"
              >
                <Bot className="w-3.5 h-3.5 text-primary shrink-0 mr-1" />
                <SelectValue placeholder="选择模型" />
              </SelectTrigger>
              <SelectContent>
                {availableModels.map(m => (
                  <SelectItem key={m.id} value={m.id} className="text-xs">
                    {m.name || m.id}{m.id === defaultModelId ? '（默认）' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Popover open={quickOpen} onOpenChange={setQuickOpen}>
            <PopoverTrigger asChild><Button type="button" variant="ghost" size="sm" disabled={isLoading || sendDisabled}><Zap className="text-amber-500" />快捷提问</Button></PopoverTrigger>
            <PopoverContent side="top" align="start" sideOffset={8} aria-label="快捷提问" className="w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl p-0">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <h2 className="flex items-center gap-2 text-base font-semibold"><Zap className="h-5 w-5 fill-blue-600 text-blue-600 dark:fill-blue-400 dark:text-blue-400" />快捷提问</h2>
                <PopoverClose asChild><Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" aria-label="关闭快捷提问"><X /></Button></PopoverClose>
              </div>
              <Tabs defaultValue="frequent">
                <TabsList aria-label="问题分类" className="h-12 w-full justify-start gap-6 rounded-none border-b bg-transparent px-4 py-0">
                  <TabsTrigger value="frequent" className="h-full rounded-none border-b-2 border-transparent px-0 data-[state=active]:border-blue-600 data-[state=active]:bg-transparent data-[state=active]:text-blue-600 data-[state=active]:shadow-none dark:data-[state=active]:border-blue-400 dark:data-[state=active]:text-blue-400">常问</TabsTrigger>
                  <TabsTrigger value="bookmarks" className="h-full rounded-none border-b-2 border-transparent px-0 data-[state=active]:border-blue-600 data-[state=active]:bg-transparent data-[state=active]:text-blue-600 data-[state=active]:shadow-none dark:data-[state=active]:border-blue-400 dark:data-[state=active]:text-blue-400">收藏</TabsTrigger>
                </TabsList>
                <TabsContent value="frequent" className="m-0 max-h-64 overflow-y-auto p-2">
                  {!frequent.length && <p className="px-2 py-6 text-sm text-muted-foreground">暂无常问问题</p>}
                  {frequent.map(q => <Button type="button" variant="ghost" key={q.id} disabled={isLoading || sendDisabled} className="h-auto w-full justify-between gap-3 whitespace-normal px-2 py-3 text-left font-normal" onClick={() => { composer.setText(q.question); setQuickOpen(false); }}><span className="min-w-0 break-words">{q.question}</span><span className="shrink-0 text-xs text-muted-foreground">{q.count} 次</span></Button>)}
                </TabsContent>
                <TabsContent value="bookmarks" className="m-0 max-h-64 overflow-y-auto p-2">
                  {!bookmarks.length && <p className="px-2 py-6 text-sm text-muted-foreground">暂无收藏问题</p>}
                  {bookmarks.map(item => <div key={item.id} className="flex items-center gap-1">
                    <Button type="button" variant="ghost" disabled={isLoading || sendDisabled} className="h-auto min-w-0 flex-1 justify-start whitespace-normal break-words px-2 py-3 text-left font-normal" onClick={() => quickAsk(item.content)}>{item.content}</Button>
                    <Button type="button" size="icon" variant="ghost" aria-label={`删除收藏 ${item.content}`} onClick={() => removeBookmark(item.id)}><Trash2 /></Button>
                  </div>)}
                </TabsContent>
              </Tabs>
            </PopoverContent>
          </Popover>
        </div>
        <div className="flex items-center gap-2">
          {configs?.voice_stt?.is_enabled && <Tooltip><TooltipTrigger asChild>
            {isRecording ? <ComposerPrimitive.StopDictation asChild><Button type="button" variant="destructive" size="icon" aria-label="停止录音"><Square /></Button></ComposerPrimitive.StopDictation>
              : <ComposerPrimitive.Dictate asChild><Button type="button" variant="ghost" size="icon" disabled={isLoading || sendDisabled} aria-label="语音输入"><Mic /></Button></ComposerPrimitive.Dictate>}
          </TooltipTrigger><TooltipContent>{isRecording ? '停止录音' : '语音输入'}</TooltipContent></Tooltip>}
          {isLoading ? <Button type="button" size="icon" variant="destructive" aria-label="停止生成" onClick={() => { void cancelPersistentRun(); }}><Square /></Button>
            : <ComposerPrimitive.Send asChild><Button size="icon" disabled={sendDisabled} aria-label="发送问题"><ArrowUp /></Button></ComposerPrimitive.Send>}
        </div>
      </div>
    </ComposerPrimitive.Root>
  </div>;
};
