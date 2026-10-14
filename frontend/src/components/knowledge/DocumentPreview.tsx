import { useEffect, useState } from 'react';
import { DocumentItem } from '../../types/knowledge';
import { apiRequest, downloadDocument } from '../../services/api';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { Alert, AlertDescription } from '../ui/alert';
import { Loader2, Download } from 'lucide-react';

interface ChunkPage {
  total: number; version: string;
  items: {id: string; content: string; chunk_index: number; metadata: {headings?: string[]; pages?: number[]}}[];
}

export function DocumentPreview({doc, onClose}: {doc: DocumentItem | null; onClose: () => void}) {
  const [page, setPage] = useState<ChunkPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => { setOffset(0); setPage(null); setError(''); }, [doc?.id]);
  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    setLoading(true); setError('');
    apiRequest<ChunkPage>(`/knowledge/documents/${doc.id}/chunks?offset=${offset}&limit=20`)
      .then(data => { if (!cancelled) setPage(data); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [doc?.id, offset]);
  return <Dialog open={!!doc} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-w-3xl max-h-[85dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>{doc?.filename}</DialogTitle><DialogDescription>
        有效切片 {page?.total ?? 0} 个{page?.version ? ` · 版本 ${page.version.slice(0,8)}` : ''}；重建期间展示旧索引。
      </DialogDescription></DialogHeader>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div>
        <Button variant="outline" size="sm" onClick={async () => {
          if (!doc) return;
          try { await downloadDocument(doc.id, doc.filename); } catch (e) { setError((e as Error).message); }
        }}>
          <Download className="w-3.5 h-3.5 mr-1.5" />
          下载原件
        </Button>
      </div>
      {loading ? (
        <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="w-4 h-4 animate-spin text-primary" />
          正在加载切片…
        </div>
      ) : page?.items.length ? (
        <div className="space-y-3">
          {page.items.map(chunk => (
            <article key={chunk.id} className="rounded-lg border border-border bg-muted/20 p-4 space-y-2">
              <p className="text-sm font-medium">切片 {chunk.chunk_index}
                {chunk.metadata.pages?.length ? ` · 第 ${chunk.metadata.pages.join('、')} 页` : ''}</p>
              <p className="text-xs text-muted-foreground">{chunk.metadata.headings?.join(' / ')}</p>
              <p className="text-sm whitespace-pre-wrap break-words">{chunk.content}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground py-4">暂无有效切片，请等待处理完成或重建索引。</p>
      )}
      <DialogFooter className="flex flex-row justify-between items-center sm:justify-between w-full pt-2">
        <Button variant="outline" size="sm" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0,offset-20))}>上一页</Button>
        <span className="text-xs text-muted-foreground">第 {Math.floor(offset/20)+1} 页</span>
        <Button variant="outline" size="sm" disabled={loading || !page || offset+20 >= page.total} onClick={() => setOffset(offset+20)}>下一页</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
