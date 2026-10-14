import { useEffect, useState } from 'react';
import { KnowledgeBase } from '../../types/knowledge';
import { apiRequest } from '../../services/api';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '../ui/alert-dialog';
import { Alert, AlertDescription } from '../ui/alert';
import { Badge } from '../ui/badge';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '../../lib/utils';

interface SearchResult {
  items: {chunk_id: string; content: string; score: number; metadata: {
    filename?: string; pages?: number[]; headings?: string[]; retrieval_sources?: string[]; vector_similarity?: number;
  }}[];
  diagnostics: {warnings: string[]; effective_mode: string; vector_candidates: number; keyword_candidates: number;
    elapsed_ms: number; score_type: string};
}
interface Task {id: string; kind?: string; status: string; attempts: number; error: string; result?: Record<string, number>}

export function KnowledgeTools({kb, refresh}: {kb: KnowledgeBase; refresh: () => void}) {
  const [panel, setPanel] = useState<'search' | 'tasks' | 'edit' | null>(null);
  const [confirm, setConfirm] = useState<'reindex' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('hybrid');
  const [threshold, setThreshold] = useState('0.25');
  const [result, setResult] = useState<SearchResult | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [maintenance, setMaintenance] = useState<Task[]>([]);
  const [name, setName] = useState(kb.name);
  const [description, setDescription] = useState(kb.description || '');
  useEffect(() => { setResult(null); setQuery(''); setPanel(null); setError(''); }, [kb.id]);
  useEffect(() => {
    if (panel !== 'tasks') return;
    let disposed = false;
    const load = async () => {
      try {
        const [jobs, upkeep] = await Promise.all([
          apiRequest<{items: Task[]}>(`/knowledge/bases/${kb.id}/jobs`), apiRequest<Task[]>('/knowledge/maintenance'),
        ]);
        if (!disposed) { setTasks(jobs.items); setMaintenance(upkeep); }
      } catch (e) { if (!disposed) setError((e as Error).message); }
    };
    void load(); const timer = setInterval(load, 3000);
    return () => { disposed = true; clearInterval(timer); };
  }, [panel, kb.id]);
  const open = (next: typeof panel) => { setError(''); setPanel(next); setName(kb.name); setDescription(kb.description || ''); };
  const statuses: Record<string,string> = {queued:'排队中',processing:'处理中',retrying:'等待重试',staged:'等待全库切换',ready:'已完成',failed:'失败'};
  return <>
    <div className="flex flex-wrap gap-2 items-center">
      <Button variant="outline" size="sm" onClick={() => open('search')}>检索调试</Button>
      <Button variant="outline" size="sm" onClick={() => open('tasks')}>处理与维护任务</Button>
      <Button variant="outline" size="sm" disabled={busy} onClick={async () => {
        setBusy(true); setError('');
        try { await apiRequest(`/knowledge/bases/${kb.id}/repair`, {method:'POST'}); toast.success('已提交索引修复任务'); open('tasks'); }
        catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>修复索引</Button>
      <Button variant="outline" size="sm" disabled={!!kb.index_batch_id} onClick={() => { setError(''); setConfirm('reindex'); }}>全库重建</Button>
      <Button variant="ghost" size="sm" onClick={() => open('edit')}>编辑知识库</Button>
      <Button variant="ghost" size="sm" className="text-destructive" disabled={!!kb.index_batch_id} onClick={() => { setError(''); setConfirm('delete'); }}>删除知识库</Button>
    </div>
    {kb.index_batch_id && <p role="status" className="text-sm text-muted-foreground">全库重建中，全部成功后切换；当前仍使用旧索引。</p>}
    {error && !panel && !confirm && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
    <Dialog open={!!panel} onOpenChange={value => { if (!value) setPanel(null); }}>
      <DialogContent className={cn(panel === 'edit' ? 'max-w-md' : 'max-w-3xl', 'max-h-[85dvh] overflow-y-auto')}>
        <DialogHeader>
          <DialogTitle>{panel === 'search' ? '检索调试' : panel === 'edit' ? '编辑知识库' : '处理与维护任务'} · {kb.name}</DialogTitle>
          <DialogDescription>
            {panel === 'search' ? '直接检查命中内容，不经过对话模型。相似度阈值仅作用于向量召回，排序分数不是相关概率。' : panel === 'tasks' ? '文档任务属于当前知识库；维护任务展示当前用户最近 50 条记录。' : '修改知识库名称和说明。'}
          </DialogDescription>
        </DialogHeader>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}

        {panel === 'edit' && <form className="space-y-4" onSubmit={async event => {
          event.preventDefault(); setBusy(true); setError('');
          try { await apiRequest(`/knowledge/bases/${kb.id}`, {method:'PATCH', body:JSON.stringify({name, description})}); setPanel(null); refresh(); toast.success('知识库已更新'); }
          catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>
          <div className="space-y-2">
            <Label htmlFor="kb-edit-name">名称</Label>
            <Input id="kb-edit-name" required maxLength={100} value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="kb-edit-description">说明</Label>
            <Textarea id="kb-edit-description" rows={4} maxLength={4000} value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setPanel(null)} disabled={busy}>取消</Button>
            <Button disabled={busy || !name.trim()} type="submit">保存修改</Button>
          </DialogFooter>
        </form>}

        {panel === 'search' && <>
          <form className="space-y-4" onSubmit={async event => {
            event.preventDefault(); setBusy(true); setError(''); setResult(null);
            try { setResult(await apiRequest<SearchResult>(`/knowledge/bases/${kb.id}/search`, {method:'POST', body:JSON.stringify({query, mode, top_k:6, min_similarity:Number(threshold)})})); }
            catch (e) { setError((e as Error).message); } finally { setBusy(false); }
          }}>
            <div className="space-y-2">
              <Label htmlFor="kb-search-query">检索问题</Label>
              <Textarea id="kb-search-query" rows={3} required maxLength={4000} value={query} onChange={e => setQuery(e.target.value)} placeholder="输入待检索的问题或关键词..." />
            </div>
            <div className="flex flex-wrap gap-3 items-end">
              <div className="space-y-1.5 flex-1 min-w-[140px]">
                <Label htmlFor="kb-search-mode">检索方式</Label>
                <Select value={mode} onValueChange={setMode}>
                  <SelectTrigger id="kb-search-mode"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hybrid">混合检索</SelectItem>
                    <SelectItem value="keyword">关键词检索</SelectItem>
                    <SelectItem value="vector">向量检索</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5 flex-1 min-w-[140px]">
                <Label htmlFor="kb-search-threshold">最低向量相似度</Label>
                <Input id="kb-search-threshold" type="number" min={-1} max={1} step={0.05} required disabled={mode==='keyword'} value={threshold} onChange={e => setThreshold(e.target.value)} />
              </div>
              <Button disabled={busy || !query.trim()} type="submit" className="gap-1.5">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {busy ? '正在检索…' : '开始检索'}
              </Button>
            </div>
          </form>
          {result && <div className="space-y-3 pt-3 border-t border-border">
            <p className="text-xs text-muted-foreground">实际方式：{result.diagnostics.effective_mode} · 向量候选 {result.diagnostics.vector_candidates} · 关键词候选 {result.diagnostics.keyword_candidates} · {result.diagnostics.elapsed_ms} ms</p>
            {result.diagnostics.warnings.map((warning,i) => <Alert key={i}><AlertDescription>{warning}</AlertDescription></Alert>)}
            {result.items.length === 0 && <p role="status" className="text-sm text-muted-foreground text-center py-6">没有命中有效证据。请调整问题、阈值或检查索引。</p>}
            {result.items.map(item => <article key={item.chunk_id} className="rounded-xl border border-border bg-muted/20 p-4 space-y-2">
              <p className="font-medium text-sm text-foreground">{item.metadata.filename} {item.metadata.pages?.length ? `· 第 ${item.metadata.pages.join('、')} 页` : ''}</p>
              <p className="text-xs text-muted-foreground">{item.metadata.headings?.join(' / ')} · 排序分 {item.score.toFixed(4)} · {item.metadata.retrieval_sources?.join(' + ')}
                {item.metadata.vector_similarity != null ? ` · 向量相似度 ${item.metadata.vector_similarity.toFixed(3)}` : ''}</p>
              <p className="whitespace-pre-wrap break-words text-sm text-foreground/90">{item.content}</p>
            </article>)}
          </div>}
        </>}

        {panel === 'tasks' && <div className="space-y-4">
          <div>
            <h4 className="font-medium text-sm text-foreground mb-2">文档处理</h4>
            {tasks.length === 0 && <p className="text-xs text-muted-foreground">暂无处理任务</p>}
            <div className="space-y-2">
              {tasks.map(task => <div key={task.id} className="border border-border bg-muted/20 rounded-xl p-3 text-sm space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs">{task.id.slice(0,8)}</span>
                  <Badge variant={task.status === 'ready' ? 'secondary' : task.status === 'failed' ? 'destructive' : 'outline'}>{statuses[task.status] || task.status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">已尝试 {task.attempts} 次</p>
                {task.error && <p className="text-xs text-destructive">{task.error}</p>}
              </div>)}
            </div>
          </div>
          <div>
            <h4 className="font-medium text-sm text-foreground mb-2">索引维护</h4>
            {maintenance.length === 0 && <p className="text-xs text-muted-foreground">暂无维护任务</p>}
            <div className="space-y-2">
              {maintenance.map(task => <div key={task.id} className="border border-border bg-muted/20 rounded-xl p-3 text-sm space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-xs">{task.kind === 'repair' ? '索引修复' : '文件与索引清理'}</span>
                  <Badge variant={task.status === 'ready' ? 'secondary' : task.status === 'failed' ? 'destructive' : 'outline'}>{statuses[task.status] || task.status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">已尝试 {task.attempts} 次</p>
                {task.result && task.kind === 'repair' && <p className="text-xs text-muted-foreground">检查 {task.result.checked_chunks} 个切片，补回 {task.result.restored_vectors} 个向量，清理 {task.result.removed_vectors} 个失效向量。</p>}
                {task.error && <p className="text-xs text-destructive">{task.error}</p>}
                {task.status === 'failed' && <Button size="sm" variant="outline" disabled={busy} onClick={async () => {
                  setBusy(true); setError('');
                  try { await apiRequest(`/knowledge/maintenance/${task.id}/retry`, {method:'POST'}); setMaintenance(items => items.map(t => t.id===task.id ? {...t,status:'queued',error:''} : t)); }
                  catch (e) { setError((e as Error).message); } finally { setBusy(false); }
                }}>重新提交</Button>}
              </div>)}
            </div>
          </div>
        </div>}
      </DialogContent>
    </Dialog>
    <AlertDialog open={!!confirm} onOpenChange={value => { if (!value && !busy) setConfirm(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{confirm === 'delete' ? '删除整个知识库？' : '重建整个知识库？'}</AlertDialogTitle>
        <AlertDialogDescription>{confirm === 'delete' ? '将删除知识库及全部文档，后台清理原件和索引。此操作无法撤销。' : '使用当前默认嵌入模型重新处理全部原件，可能产生模型调用费用。全部成功后一次切换，失败保留旧索引。期间不能上传或删除文档。'}</AlertDialogDescription></AlertDialogHeader>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        <AlertDialogFooter><AlertDialogCancel disabled={busy}>取消</AlertDialogCancel><AlertDialogAction disabled={busy} className={confirm === 'delete' ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : ''} onClick={async event => {
          event.preventDefault(); setBusy(true); setError('');
          try { await apiRequest(`/knowledge/bases/${kb.id}${confirm==='reindex' ? '/reindex' : ''}`, {method:confirm==='delete' ? 'DELETE' : 'POST'});
            toast.success(confirm==='delete' ? '知识库已删除，后台清理文件与索引' : '已提交全库重建'); setConfirm(null); refresh();
          } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>{busy ? '正在提交…' : '确认'}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </>;
}
