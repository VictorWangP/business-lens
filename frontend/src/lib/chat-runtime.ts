import type { ThreadMessageLike } from '@assistant-ui/react';
import type { Message } from '../types/chat';
import { cleanAssistantAnswer } from './answer-presentation';

// Keep all query/citation evidence on the host message, while exposing text and tools to assistant-ui.
export function toRuntimeMessage(message: Message, isRunning = false, userQuery = ''): ThreadMessageLike {
  const visibleText = message.role === 'assistant'
    ? cleanAssistantAnswer(message.content, userQuery)
    : message.content;
  const content: Exclude<ThreadMessageLike['content'], string>[number][] = [{ type: 'text', text: visibleText }];
  if (message.role === 'assistant') {
    if (message.tool_calls?.metrics?.length) content.push({
      type: 'tool-call', toolCallId: `${message.id}:metrics`, toolName: 'render_metrics',
      args: { metrics: message.tool_calls.metrics as any }, result: { available: true },
    });
    if (message.tool_calls?.chart) content.push({
      type: 'tool-call', toolCallId: `${message.id}:chart`, toolName: 'render_chart',
      args: { chart: message.tool_calls.chart as any }, result: { available: true },
    });
  }
  const state = message.tool_calls?.status;
  const status: ThreadMessageLike['status'] = state === 'cancelled' ? { type: 'incomplete', reason: 'cancelled' }
    : state === 'failed' ? { type: 'incomplete', reason: 'error' }
    : isRunning && !['completed', 'partial'].includes(state || '') ? { type: 'running' }
    : { type: 'complete', reason: 'stop' };
  return { id: message.id, role: message.role, content, createdAt: new Date(message.created_at),
    ...(message.role === 'assistant' ? { status } : {}), metadata: { custom: { appMessage: message } } };
}
