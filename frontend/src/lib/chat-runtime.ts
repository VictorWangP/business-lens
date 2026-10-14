import type { ThreadMessage, ThreadMessageLike, ThreadAssistantMessagePart } from '@assistant-ui/react';
import type { Message } from '../types/chat';

// Domain projection only. assistant-ui owns live message aggregation and protocol parsing.
export function toRuntimeMessage(message: Message): ThreadMessageLike {
  const content: any[] = [{type:'text', text:message.content}];
  if (message.tool_calls?.presentation) content.push({type:'data', name:'agui-activity/business-answer', data:message.tool_calls.presentation});
  const events = message.execution_events || [];
  for (const event of events.filter(event => event.type === 'tool_start')) content.push({
    type:'tool-call', toolCallId:event.tool_id, toolName:event.name, args:{}, argsText:'{}',
    ...(events.some(end => end.type === 'tool_end' && end.tool_id === event.tool_id) ? {result:{status:'completed'}} : {}),
  });
  const status=message.tool_calls?.status;
  return {id:message.id, role:message.role, content, createdAt:new Date(message.created_at),
    ...(message.role === 'assistant' ? {status:status==='failed' || status==='cancelled' ? {type:'incomplete' as const,reason:status==='cancelled' ? 'cancelled' as const : 'error' as const} : {type:'complete' as const, reason:'stop' as const}} : {}),
    metadata:{custom:{run_id:message.tool_calls?.run_id, status:message.tool_calls?.status}}};
}

export function fromRuntimeMessage(message: ThreadMessage, conversationId=''): Message {
  const parts=message.content as readonly ThreadAssistantMessagePart[];
  const part = parts.find(part => part.type === 'data' && part.name === 'agui-activity/business-answer');
  const data: any = part?.type === 'data' ? part.data : undefined;
  const tools = parts.filter(part => part.type === 'tool-call');
  return {id:message.id, conversation_id:conversationId, role:message.role as Message['role'],
    content:message.content.filter(part => part.type === 'text').map(part => part.type === 'text' ? part.text : '').join('\n'),
    created_at:message.createdAt.toISOString(), citations:data?.citations,
    tool_calls:{presentation:data, answer:data?.answer, run_id:message.metadata.custom.run_id as string,
      status:message.status?.type === 'running' ? 'running' : message.status?.type === 'incomplete' ? 'failed' : 'completed'},
    execution_events:data?.operations || tools.flatMap(tool => [
      {type:'tool_start',name:tool.toolName,tool_id:tool.toolCallId},
      ...(tool.result !== undefined ? [{type:'tool_end',name:tool.toolName,tool_id:tool.toolCallId}] : []),
    ])};
}
