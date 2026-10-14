import React, { useState, useEffect, useRef } from 'react';
import { Button } from '../ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Label } from '../ui/label';
import { Badge } from '../ui/badge';
import { Alert, AlertDescription } from '../ui/alert';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '../ui/alert-dialog';
import { toast } from 'sonner';
import { Progress } from '../ui/progress';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import {
  Database,
  Plus,
  UploadCloud,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Trash2,
  Clock
} from 'lucide-react';
import { KnowledgeBase, DocumentItem } from '../../types/knowledge';
import { apiRequest } from '../../services/api';
import { DocumentPreview } from './DocumentPreview';
import { KnowledgeTools } from './KnowledgeTools';

export const KnowledgeView: React.FC = () => {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [activeKb, setActiveKb] = useState<KnowledgeBase | null>(null);
  const activeKbId = useRef<string | undefined>(undefined);
  activeKbId.current = activeKb?.id;
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [previewDoc, setPreviewDoc] = useState<DocumentItem | null>(null);
  const [error, setError] = useState('');
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const reportError = (err: unknown) => setError(err instanceof Error ? err.message : '操作失败');
  const [uploading, setUploading] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 加载知识库列表
  const fetchKbs = async () => {
    try {
      const data = await apiRequest<KnowledgeBase[]>('/knowledge/bases');
      setKnowledgeBases(data);
      setActiveKb(current => current ? data.find(kb => kb.id === current.id) || data[0] || null : data[0] || null);
    } catch (err) {
      reportError(err);
    }
  };

  // 加载文档列表
  const fetchDocs = async (kbId: string) => {
    try {
      const data = await apiRequest<DocumentItem[]>(`/knowledge/bases/${kbId}/documents`);
      if (activeKbId.current === kbId) setDocuments(data);
    } catch (err) {
      reportError(err);
    }
  };

  useEffect(() => {
    fetchKbs();
  }, []);

  useEffect(() => {
    if (activeKb) {
      fetchDocs(activeKb.id);
    } else {
      setDocuments([]);
    }
  }, [activeKb]);

  // 轮询刷新正在解析/索引中的文档状态
  useEffect(() => {
    const hasPending = documents.some(
      (d) => ['queued','parsing','indexing','retrying','staged'].includes(d.status)
    );
    if (!hasPending || !activeKb) return;

    const timer = setInterval(() => {
      fetchDocs(activeKb.id);
      fetchKbs();
    }, 2000);

    return () => clearInterval(timer);
  }, [documents, activeKb]);

  // 创建新知识库
  const handleCreateKb = async () => {
    if (!newKbName.trim()) return;
    try {
      const created = await apiRequest<KnowledgeBase>('/knowledge/bases', {
        method: 'POST',
        body: JSON.stringify({ name: newKbName.trim(), description: newKbDesc.trim() }),
      });
      setKnowledgeBases([created, ...knowledgeBases]);
      setActiveKb(created);
      setNewKbName('');
      setNewKbDesc('');
      setShowCreateModal(false); toast.success('知识库已创建');
    } catch (err) {
      reportError(err);
    }
  };

  // 上传文档
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !activeKb) return;

    setUploading(true); setError('');
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const formData = new FormData();
      formData.append('file', file);

      try {
        await apiRequest(`/knowledge/bases/${activeKb.id}/documents/upload`, {
          method: 'POST',
          body: formData,
        });
      } catch (err) {
        reportError(err);
      }
    }
    setUploading(false);
    fetchDocs(activeKb.id);
    fetchKbs();
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getStatusBadge = (doc: DocumentItem) => {
    const states: Record<string, {label: string; Icon: typeof Clock; className: string}> = {
      ready: {label:'已就绪', Icon:CheckCircle2, className:'text-emerald-600 bg-emerald-50 dark:bg-emerald-950/60'},
      parsing: {label:`文档解析中 (${doc.progress}%)`, Icon:Loader2, className:'text-primary bg-primary/10'},
      indexing: {label:`向量索引中 (${doc.progress}%)`, Icon:Loader2, className:'text-purple-600 bg-purple-50 dark:bg-purple-950/60'},
      staged: {label:'等待全库切换', Icon:Clock, className:'text-primary bg-primary/10'},
      needs_reindex: {label:'待重建索引', Icon:Clock, className:'text-amber-600 bg-amber-50 dark:bg-amber-950/60'},
      failed: {label:'解析失败', Icon:AlertCircle, className:'text-destructive bg-destructive/10'},
    };
    const state = states[doc.status] || {label:doc.status === 'retrying' ? '重试中' : '排队中', Icon:Clock, className:'text-muted-foreground'};
    return <Badge variant="secondary" className={`gap-1 ${state.className}`}><state.Icon className={`h-3.5 w-3.5 ${['parsing','indexing'].includes(doc.status) ? 'animate-spin' : ''}`} />{state.label}</Badge>;
  };

  return (
    <div className="min-h-full bg-background text-foreground p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold text-muted-foreground tracking-wider">
            数据管理 / 知识库
          </div>
          <h2 className="text-xl font-bold text-foreground mt-1">
            企业知识库管理
          </h2>
        </div>

        <Button
          onClick={() => setShowCreateModal(true)}
          className="gap-1.5"
        >
          <Plus className="w-4 h-4" />
          <span>新建知识库</span>
        </Button>
      </div>

      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* 左侧：知识库列表 */}
        <div className="lg:col-span-1 space-y-2">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            我的知识库 ({knowledgeBases.length})
          </div>

          <div className="space-y-2">
            {knowledgeBases.map((kb) => {
              const isActive = activeKb?.id === kb.id;
              return (
                <div
                  key={kb.id}
                  onClick={() => setActiveKb(kb)}
                  className={`p-3.5 rounded-xl border cursor-pointer transition ${
                    isActive
                      ? 'border-primary bg-primary/5 ring-1 ring-primary'
                      : 'border-border bg-card hover:border-primary/50 text-card-foreground'
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <Database className={`w-4 h-4 ${isActive ? 'text-primary' : 'text-muted-foreground'}`} />
                    <span className="font-semibold text-sm text-foreground truncate">
                      {kb.name}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1.5 flex justify-between">
                    <span>{kb.document_count} 个文档</span>
                    <span>{new Date(kb.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 右侧：文档上传与分析进度看板 */}
        <div className="lg:col-span-3 space-y-4">
          {activeKb ? (
            <>
              <KnowledgeTools key={activeKb.id} kb={activeKb} refresh={() => { void fetchKbs(); void fetchDocs(activeKb.id); }} />
              {/* 上传拖拽区 */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-border hover:border-primary rounded-2xl p-8 text-center bg-card hover:bg-accent/40 cursor-pointer transition group"
              >
                <Input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.docx,.pptx,.xlsx,.html,.txt,.md,.csv"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mx-auto mb-3 group-hover:scale-105 transition">
                  {uploading ? (
                    <Loader2 className="w-6 h-6 animate-spin" />
                  ) : (
                    <UploadCloud className="w-6 h-6" />
                  )}
                </div>
                <h4 className="text-sm font-semibold text-foreground">
                  {uploading ? '正在上传并启动解析流水线...' : '点击上传文档'}
                </h4>
                <p className="text-xs text-muted-foreground mt-1">
                  支持 PDF、DOCX、PPTX、XLSX、HTML、Markdown、CSV、TXT；TXT 使用文本解析，其他格式使用 Docling
                </p>
              </div>

              {/* 文档进度列表看板 */}
              <Card className="rounded-2xl overflow-hidden shadow-sm">
                <CardHeader className="px-6 py-4 border-b border-border">
                  <CardTitle className="font-semibold text-sm text-foreground">
                    知识库文档清单与分析进度 ({documents.length})
                  </CardTitle>
                </CardHeader>

                {documents.length === 0 ? (
                  <CardContent className="p-12 text-center text-xs text-muted-foreground">
                    该知识库暂未上传任何文档，请点击上方区域上传。
                  </CardContent>
                ) : (
                  <div className="divide-y divide-border">
                    {documents.map((doc) => (
                      <div key={doc.id} className="p-4 space-y-2 hover:bg-accent/40 transition">
                        <div className="flex flex-wrap gap-3 items-center justify-between">
                          <div className="flex items-center space-x-3">
                            <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center text-muted-foreground">
                              <FileText className="w-4 h-4" />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-foreground">
                                {doc.filename}
                              </div>
                              <div className="text-[11px] text-muted-foreground">
                                大小: {formatFileSize(doc.file_size)} • 切片数: {doc.chunk_count}
                              </div>
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center gap-2">
                            {getStatusBadge(doc)}
                            <Button variant="ghost" size="sm" onClick={() => setPreviewDoc(doc)}>查看切片</Button>
                            {['ready','failed','needs_reindex'].includes(doc.status) && <Button disabled={!!activeKb.index_batch_id} variant="ghost" className="text-xs text-primary" onClick={async () => {
                              try { await apiRequest(`/knowledge/documents/${doc.id}/reindex`, {method:'POST'}); toast.success('已提交重建索引任务'); await fetchDocs(activeKb.id); }
                              catch (e) { reportError(e); }
                            }}>重建索引</Button>}
                            <Button disabled={!!activeKb.index_batch_id} variant="ghost" size="icon" aria-label={`删除文档 ${doc.filename}`} className="text-destructive" onClick={() => setPendingDelete(doc)}><Trash2 className="w-4 h-4"/></Button>
                          </div>
                        </div>

                        {doc.error_msg && <Alert variant="destructive"><AlertDescription>{doc.error_msg}</AlertDescription></Alert>}
                        {/* 进度条 */}
                        {!['ready','failed','needs_reindex'].includes(doc.status) && (
                          <Progress value={doc.progress} aria-label={`${doc.filename} 处理进度`} className="h-1.5" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </>
          ) : (
            <div className="p-12 text-center text-muted-foreground border border-border rounded-2xl bg-card">
              请选择或创建一个知识库以查看详情
            </div>
          )}
        </div>
      </div>

      <DocumentPreview doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      <AlertDialog open={!!pendingDelete} onOpenChange={open => { if (!open && !deleting) setPendingDelete(null); }}>
        <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>删除文档？</AlertDialogTitle><AlertDialogDescription>将删除“{pendingDelete?.filename}”及其索引，此操作无法撤销。</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel><AlertDialogAction disabled={deleting} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={async e => {
            e.preventDefault(); if (!pendingDelete) return; setDeleting(true); setError('');
            try { await apiRequest(`/knowledge/documents/${pendingDelete.id}`, {method:'DELETE'}); setDocuments(items => items.filter(item => item.id !== pendingDelete.id)); setPendingDelete(null); toast.success('文档已删除'); await fetchKbs(); }
            catch (err) { reportError(err); } finally { setDeleting(false); }
          }}>{deleting ? '正在删除…' : '确认删除'}</AlertDialogAction></AlertDialogFooter>
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        </AlertDialogContent>
      </AlertDialog>
      {/* 新建知识库弹窗 */}
      <Dialog open={showCreateModal} onOpenChange={setShowCreateModal}>
          <DialogContent className="max-w-md">
            <DialogHeader><DialogTitle>新建知识库</DialogTitle><DialogDescription>输入知识库名称和说明。</DialogDescription></DialogHeader>

            {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
            <div className="space-y-3">
              <div>
                <Label htmlFor="knowledge-name" className="text-xs font-semibold mb-1 block">
                  知识库名称
                </Label>
                <Input
                  id="knowledge-name"
                  type="text"
                  placeholder="如：财务制度合规库、产品技术手册"
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                />
              </div>

              <div>
                <Label htmlFor="knowledge-description" className="text-xs font-semibold mb-1 block">
                  描述说明
                </Label>
                <Textarea
                  id="knowledge-description"
                  rows={3}
                  placeholder="介绍知识库收录的文档范围与应用场景..."
                  value={newKbDesc}
                  onChange={(e) => setNewKbDesc(e.target.value)}
                />
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" size="sm"
                onClick={() => setShowCreateModal(false)}
              >
                取消
              </Button>
              <Button size="sm"
                onClick={handleCreateKb}
              >
                立即创建
              </Button>
            </DialogFooter>
          </DialogContent>
      </Dialog>
    </div>
  );
};
