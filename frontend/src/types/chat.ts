export interface MetricCard {
  label: string;
  value: string;
  change?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export interface ChartConfig {
  type: 'bar' | 'line' | 'area' | 'pie';
  title: string;
  x_key: string;
  y_keys: string[];
  data: Record<string, any>[];
}

export interface CitationItem {
  id: string;
  doc_id: string;
  doc_name: string;
  chunk_index: number;
  content: string;
  score?: number;
  chunk_id?: string;
  version?: string;
  pages?: number[];
  headings?: string[];
  retrieval_warning?: string;
}

export interface FinalAnswer {
  version: 1;
  sections: {title: string; summary: string; query_id?: string | null; show_table?: boolean;
    code?: {language: string; content: string} | null}[];
  suggestions: string[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tool_calls?: {
    metrics?: MetricCard[];
    chart?: ChartConfig;
    run_id?: string;
    status?: string;
    last_sequence?: number;
    query_results?: {query_id: string; citation_id?: string; source_name: string; retrieved_at: string; rows: Record<string, any>[]; truncated: boolean; sql: string; parameters?: Record<string, unknown>}[];
    suggestions?: string[];
    answer?: FinalAnswer;
  };
  citations?: CitationItem[];
  execution_events?: {type: string; name?: string; message?: string}[];
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  kb_ids: string[];
  source_ids?: string[];
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
