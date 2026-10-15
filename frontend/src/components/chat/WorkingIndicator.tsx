import React, { useContext, useEffect, useState } from 'react';
import { RunTimingContext } from './RunTimingContext';
import { Loader2 } from 'lucide-react';
import { Message } from '../../types/chat';
import { executionEvents } from '../../lib/chat-runtime';

const toolLabels: Record<string, string> = {
  list_available_resources: '正在确认可用资源',
  get_business_schema: '正在读取业务字段',
  query_metrics: '正在查询业务指标',
  execute_readonly_sql: '正在查询业务数据',
};

function elapsedSecondsSince(createdAt: string) {
  // Backend timestamps are naive UTC; parse them as UTC instead of browser local time.
  const timestamp = Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(createdAt) ? createdAt : `${createdAt}Z`);
  return Number.isFinite(timestamp) ? Math.max(0, Math.floor((Date.now() - timestamp) / 1000)) : 0;
}

export function WorkingIndicator({ message }: { message: Message }) {
  const resumedStartedAt = useContext(RunTimingContext);
  const startedAt = resumedStartedAt ?? message.created_at;
  const [seconds, setSeconds] = useState(() => elapsedSecondsSince(startedAt));
  useEffect(() => {
    const updateElapsed = () => setSeconds(elapsedSecondsSince(startedAt));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  const events = executionEvents(message);
  const latest = events[events.length - 1];
  const label = latest?.type === 'tool_start' ? toolLabels[latest.name || ''] || '正在执行工具'
    : message.content ? '正在生成回答' : latest ? '正在分析结果并整理回答' : '正在思考并准备回答';
  return <div className="mt-3 flex items-center gap-2 rounded-xl bg-primary/10 px-3 py-2 text-sm text-primary">
    <Loader2 aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin" />
    <span role="status" aria-live="polite">{label}…</span>
    <span aria-hidden="true" className="ml-auto text-xs tabular-nums">{seconds} 秒</span>
  </div>;
}
