import type { Message } from './chat';
export type FeedbackStatus = 'pending' | 'resolved';
export type FeedbackReason = 'data_error' | 'irrelevant' | 'citation_error' | 'presentation_error' | 'other';
export const reasonLabels: Record<FeedbackReason, string> = {
  data_error:'数据/计算错误', irrelevant:'回答与问题不符', citation_error:'引用/依据有误', presentation_error:'图表/表格有误', other:'其他',
};
export const statusLabels: Record<FeedbackStatus, string> = {pending:'待处理', resolved:'已处理'};
export interface FeedbackSummary {id:string; message_id:string; status:FeedbackStatus; created_at:string; deduplicated?:boolean}
export interface FeedbackItem {id:string; user:{id:string; name:string}; question:string; created_at:string; status:FeedbackStatus; version:number}
export interface FeedbackPage {items:FeedbackItem[]; total:number; page:number; page_size:number}
export interface FeedbackDetail extends FeedbackItem {
  reason:FeedbackReason; user_comment:string; processing_note:string; last_handled_by:string|null; last_handled_at:string|null; original_deleted:boolean;
  evidence_snapshot: {
    schema_version:number;
    answer:{content:string; structured:unknown; metrics:NonNullable<Message['tool_calls']>['metrics']; chart:NonNullable<Message['tool_calls']>['chart']; citations:Message['citations']};
    context:{question_message_id:string; history:{role:string; content:string}[]};
    resource:{workspace_id:string|null; workspace_name:string|null; scope_version:number; kb_ids:string[]; source_ids:string[]};
    execution:{model:string; status:string; created_at:string; finished_at:string|null; queries:NonNullable<Message['tool_calls']>['query_results']};
  };
  history:{version:number; action:string; actor_id:string|null; actor_name:string; from_status:FeedbackStatus|null; to_status:FeedbackStatus; old_note:string; new_note:string; created_at:string}[];
}
export function feedbackTime(value:string|null) {
  if (!value) return '尚未处理';
  return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value));
}
export function errorStatus(error:unknown):number|undefined {return (error as {status?:number})?.status;}
export function errorMessage(error:unknown) {return error instanceof Error ? error.message : '请求失败，请重试';}
