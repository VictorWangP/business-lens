export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  document_count: number;
  index_batch_id?: string;
  created_at: string;
}

export interface DocumentItem {
  id: string;
  kb_id: string;
  filename: string;
  file_size: number;
  status: 'queued' | 'parsing' | 'indexing' | 'staged' | 'ready' | 'failed' | 'retrying' | 'needs_reindex';
  progress: number;
  error_msg: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}
