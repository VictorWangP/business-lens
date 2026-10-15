import type {ReadonlyJSONObject} from 'assistant-stream/utils';

export interface MetricCard {
  label: string;
  value: string;
  change?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export interface ChartConfig {
  type: 'bar' | 'line' | 'pie';
  title: string;
  x_key: string;
  y_keys: string[];
  data: Record<string, string | number | null>[];
}

export interface FinalAnswer {
  version: 1;
  sections: {title: string; summary: string; query_id?: string | null; show_table?: boolean;
    code?: {language: string; content: string} | null}[];
  suggestions: string[];
}

export interface ExecutionResult {
  status?: string; source_id?: string; source_name?: string; sql?: string;
  metric?: string; definition?: string; row_count?: number; truncated?: boolean;
  sources?: {id: string; name: string}[]; error?: string;
}

export interface ExecutionEvent {
  type: string; name?: string; tool_id?: string; message?: string;
  args?: ReadonlyJSONObject; result?: ExecutionResult;
}

export interface QueryEvidence {
  query_id: string;
  citation_id: string;
  source_id?: string;
  source_name: string;
  retrieved_at?: string;
  rows: Record<string, unknown>[];
  truncated: boolean;
  sql?: string;
  parameters?: Record<string, unknown>;
  chart?: ChartConfig | null;
  metrics?: MetricCard[];
}

export interface BusinessPresentation {
  answer: FinalAnswer;
  queries: QueryEvidence[];
  operations?: ExecutionEvent[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tool_calls?: {
    presentation?: BusinessPresentation;
    run_id?: string;
    status?: string;
    last_sequence?: number;
    interrupts?: {id:string; reason?:string; message?:string; [key:string]:any}[];
    execution_events?: ExecutionEvent[];
  };
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  workspace_id?: string | null;
  scope_version?: number;
  is_pinned?: boolean;
  created_at: string;
  updated_at: string;
}

export interface BookmarkItem {
  id: string;
  content: string;
  created_at: string;
}
