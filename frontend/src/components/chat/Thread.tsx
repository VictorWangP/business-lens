import React from 'react';
import {useAuiState} from '@assistant-ui/react';
import {useAgUiInterrupts} from '@assistant-ui/react-ag-ui';
import {fromRuntimeMessage} from '../../lib/chat-runtime';
import {InterruptPrompt} from './InterruptPrompt';
import { ThreadPrimitive } from '@assistant-ui/react';
import { Sparkles, ArrowRight, ArrowDown, PanelLeftOpen } from 'lucide-react';
import { MessageItem } from './MessageItem';
import { Composer } from './Composer';
import { useConfig } from '../../context/ConfigContext';
import { Button } from '../ui/button';

interface ThreadProps {
  sourceIds?: string[];


  workspaceId?: string;
  workspaceVersion?: number;
  workspaceWarning?: string;
  workspaceActionLabel?: string;
  onWorkspaceAction?: () => void;
  composerKey?: string;
  sendDisabled?: boolean;

  threadListCollapsed?: boolean;
  onToggleThreadList?: () => void;
  selectedModel?: string;
  onModelChange?: (model: string) => void;
}

export const Thread: React.FC<ThreadProps> = ({
  sourceIds,
  sendDisabled,
  workspaceWarning, workspaceActionLabel, onWorkspaceAction,
  composerKey, workspaceId, workspaceVersion,
  threadListCollapsed = false,
  onToggleThreadList,
  selectedModel,
  onModelChange,
}) => {
  const { configs } = useConfig();
  const interrupts = useAgUiInterrupts();
  const hasInterrupts = interrupts.length > 0;
  const messages=useAuiState(s=>s.thread.messages);
  const isLoading=useAuiState(s=>s.thread.isRunning);
  const last=messages[messages.length-1];
  const suggestions=last ? fromRuntimeMessage(last).tool_calls?.presentation?.answer.suggestions || [] : [];
  // 配置动态联动
  const enableWelcome = configs?.welcome_setting?.is_enabled ?? true;
  const greeting = configs?.welcome_setting?.greeting || '你好';
  const assistantName = configs?.welcome_setting?.assistant_name || '我是经管之星·AI问数助手';
  const welcomeDesc =
    configs?.welcome_setting?.description ||
    '欢迎使用智能AI问数，您可以向我咨询经营数据、报表分析相关问题。';

  // 手工推荐来自开场白配置，与自动常问统计分开。
  const welcomeQuestions = configs?.welcome_setting?.questions ?? [];

  const enableNext = configs?.next_questions?.is_enabled ?? true;

  return (
    <ThreadPrimitive.Root className="relative flex-1 h-full flex flex-col justify-between overflow-hidden bg-background text-foreground transition-colors">
      {/* 折叠时显示的“展开会话列表”快捷入口 */}
      {threadListCollapsed && onToggleThreadList && (
        <Button variant="outline" size="sm"
          onClick={onToggleThreadList}
          title="展开会话列表"
          className="absolute left-4 top-3.5 z-10 flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg border-border bg-background/95 backdrop-blur-sm shadow-sm text-xs font-medium text-muted-foreground hover:text-foreground transition"
        >
          <PanelLeftOpen className="w-3.5 h-3.5 text-primary" />
          <span>展开会话</span>
        </Button>
      )}

      {/* 滚动消息区 */}
      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 custom-scrollbar">
        {workspaceWarning && (
          <div role="status" className="mx-auto mb-4 flex w-full max-w-3xl items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-foreground">
            <div className="min-w-0 space-y-1">
              <p>{workspaceWarning}</p>
            </div>
            {workspaceActionLabel && onWorkspaceAction && (
              <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={onWorkspaceAction}>
                {workspaceActionLabel}
              </Button>
            )}
          </div>
        )}
        {messages.length === 0 ? (
          // 空会话状态：1:1 还原第二张截图的优雅开场白视觉效果
          <div className="h-full flex flex-col items-center justify-center max-w-3xl mx-auto text-center px-4 py-8 animate-in fade-in duration-300">
            {enableWelcome && (
              <div className="space-y-3">
                {/* 1. 你好 (大标题) */}
                <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-foreground">
                  {greeting}
                </h1>

                {/* 2. 我是经管之星·AI问数助手 */}
                <h2 className="text-lg sm:text-xl font-bold text-primary tracking-tight pt-1">
                  {assistantName}
                </h2>

                {/* 3. 开场白文案 */}
                <p className="text-sm sm:text-base text-muted-foreground max-w-lg mx-auto leading-relaxed pt-1">
                  {welcomeDesc}
                </p>

                {welcomeQuestions.length > 0 && (
                  <>
                    {/* 4. 你可以这么问我 */}
                    <div className="pt-8 pb-3">
                      <h3 className="text-base font-bold text-foreground">
                        你可以这么问我
                      </h3>
                    </div>

                    {/* 5. 胶囊问题列表 (对标截图 2：药丸气泡按钮，微阴影，柔和圆角) */}
                    <div className="flex flex-wrap justify-center gap-3.5 max-w-2xl mx-auto pt-1">
                      {welcomeQuestions.map((q, idx) => (
                        <ThreadPrimitive.Suggestion key={idx} prompt={q} send asChild><Button variant="outline"
                          className="px-6 py-3 rounded-full border-border bg-card text-card-foreground shadow-sm hover:shadow-md hover:border-primary hover:text-primary transition-all transform hover:-translate-y-0.5 active:translate-y-0"
                        >
                          {q}
                        </Button></ThreadPrimitive.Suggestion>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ) : (
          // 消息流列表
          <div className="max-w-4xl mx-auto space-y-4">
            <ThreadPrimitive.Messages>{({ message }) => {
              const original = fromRuntimeMessage(message, workspaceId);
              return <MessageItem message={original} isWorking={message.status?.type === 'running'} />;
            }}</ThreadPrimitive.Messages>

            {/* 下一步问题建议（受应用配置开关控制，AI 响应完后展示延伸问题提示条） */}
            {enableNext && !isLoading && suggestions.length > 0 && (
              <div className="pt-2 pb-4 pl-12 space-y-2 animate-in fade-in duration-200">
                <div className="text-xs font-semibold text-muted-foreground flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-blue-500" />
                  <span>推荐延伸提问：</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <>{suggestions.map(prompt => <ThreadPrimitive.Suggestion key={prompt} prompt={prompt} send asChild>
                    <Button
                      variant="outline"
                      className="h-auto py-1.5 px-3 rounded-full text-xs text-foreground/90 bg-background hover:bg-accent hover:text-primary border-border/80 shadow-sm transition-all hover:shadow hover:-translate-y-0.5 active:translate-y-0 flex items-center gap-1.5 group"
                    >
                      <span className="font-normal">{prompt}</span>
                      <ArrowRight className="h-3 w-3 text-muted-foreground group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
                    </Button>
                  </ThreadPrimitive.Suggestion>)}</>
                </div>
              </div>
            )}


          </div>
        )}
      <ThreadPrimitive.ScrollToBottom asChild><Button variant="outline" size="icon" aria-label="回到最新回答" className="absolute bottom-40 right-6 rounded-full shadow-md"><ArrowDown /></Button></ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>

      <InterruptPrompt />
      {/* 底部输入框 */}
      <Composer
        workspaceId={workspaceId}
        workspaceVersion={workspaceVersion}
        composerKey={composerKey}
        sendDisabled={sendDisabled || hasInterrupts}
        sourceIds={sourceIds}
        isLoading={isLoading}
        selectedModel={selectedModel}
        onModelChange={onModelChange}
      />
    </ThreadPrimitive.Root>
  );
};
