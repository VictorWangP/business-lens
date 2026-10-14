import React, { useEffect, useState } from 'react';
import { apiRequest } from '../../services/api';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Checkbox } from '../ui/checkbox';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Alert, AlertDescription } from '../ui/alert';
import type { DataSource } from '../data/DataSourcesPanel';
import type { KnowledgeBase } from '../../types/knowledge';

export interface Workspace {
  id: string; name: string; version: number; kb_ids: string[]; source_ids: string[];
  status: 'ready' | 'empty' | 'invalid'; unavailable_kb_ids: string[]; unavailable_source_ids: string[];
}
interface Props {
  workspaces: Workspace[]; knowledgeBases: KnowledgeBase[]; dataSources: DataSource[];
  editRequest: {id: string; sequence: number} | null;
  onSaved: (workspace: Workspace) => void; onStart: (id: string) => void;
  onReturn: () => void; onManage: (tab: 'data' | 'knowledge') => void;
}
export function WorkspacesView({workspaces, knowledgeBases, dataSources, editRequest, onSaved, onStart, onReturn, onManage}: Props) {
  const [form, setForm] = useState<{id?: string; version?: number; name: string; kb_ids: string[]; source_ids: string[]} | null>(null);
  const [search, setSearch] = useState({kb:'', source:''});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const edit = (workspace?: Workspace) => {
    setForm(workspace ? {...workspace, kb_ids:[...workspace.kb_ids], source_ids:[...workspace.source_ids]} : {name:'',kb_ids:[],source_ids:[]});
    setSearch({kb:'',source:''}); setError('');
  };
  useEffect(() => {
    if (!editRequest) return;
    const workspace = workspaces.find(w => w.id === editRequest.id);
    if (workspace) edit(workspace);
  }, [editRequest]);
  const toggle = (field: 'kb_ids' | 'source_ids', id: string) => setForm(current => current && ({...current,
    [field]: current[field].includes(id) ? current[field].filter(x => x !== id) : [...current[field], id]}));
  const missingKbs = form?.kb_ids.filter(id => !knowledgeBases.some(k => k.id === id)) || [];
  const missingSources = form?.source_ids.filter(id => !dataSources.some(s => s.id === id)) || [];
  const save = async () => {
    if (!form || busy) return;
    setBusy(true); setError('');
    try {
      const updated = await apiRequest<Workspace>(form.id ? `/workspaces/${form.id}` : '/workspaces', {
        method:form.id ? 'PUT' : 'POST', body:JSON.stringify({name:form.name.trim(), kb_ids:form.kb_ids, source_ids:form.source_ids, version:form.version}),
      });
      onSaved(updated); setForm(null);
    } catch (e: any) { setError(e.message || '保存失败，请重试'); }
    finally { setBusy(false); }
  };
  return <section className="mx-auto w-full max-w-5xl space-y-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-semibold">业务空间</h1><p className="mt-1 text-sm text-muted-foreground">集中配置问数与知识问答的业务范围，会话自动使用绑定空间的来源。</p></div>
      <div className="flex gap-2"><Button variant="outline" onClick={onReturn}>返回对话</Button>{!form && <Button onClick={() => edit()}>新建业务空间</Button>}</div>
    </div>
    {form ? <Card><CardHeader><CardTitle role="heading" aria-level={2}>{form.id ? '编辑业务空间' : '新建业务空间'}</CardTitle></CardHeader><CardContent className="space-y-6">
      <div className="space-y-2"><Label htmlFor="workspace-name">空间名称</Label><Input id="workspace-name" value={form.name} maxLength={100} disabled={busy} onChange={e => setForm({...form,name:e.target.value})} placeholder="例如：销售分析" /></div>
      <div className="grid gap-6 md:grid-cols-2">
        <fieldset disabled={busy} className="space-y-3"><legend className="font-medium">关联业务数据源（已选 {form.source_ids.length} 个）</legend>
          <Input aria-label="搜索业务数据源" placeholder="搜索业务数据源" value={search.source} onChange={e => setSearch({...search,source:e.target.value})} />
          <div className="max-h-64 space-y-2 overflow-y-auto rounded-md border p-3">
            {dataSources.filter(s => s.name.toLowerCase().includes(search.source.toLowerCase())).map(s => <label key={s.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.source_ids.includes(s.id)} onCheckedChange={() => toggle('source_ids',s.id)} />{s.name}</label>)}
            {!dataSources.length && <p className="text-sm text-muted-foreground">暂无可关联的业务数据源</p>}
            {missingSources.map(id => <label key={id} className="flex items-center gap-2 text-sm text-destructive"><Checkbox checked onCheckedChange={() => toggle('source_ids',id)} />已失效或无权限的数据源（移除关联）</label>)}
          </div>
          <Button variant="link" className="px-0" onClick={() => onManage('data')}>管理业务数据</Button>
        </fieldset>
        <fieldset disabled={busy} className="space-y-3"><legend className="font-medium">关联知识库（已选 {form.kb_ids.length} 个）</legend>
          <Input aria-label="搜索知识库" placeholder="搜索知识库" value={search.kb} onChange={e => setSearch({...search,kb:e.target.value})} />
          <div className="max-h-64 space-y-2 overflow-y-auto rounded-md border p-3">
            {knowledgeBases.filter(k => k.name.toLowerCase().includes(search.kb.toLowerCase())).map(k => <label key={k.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.kb_ids.includes(k.id)} onCheckedChange={() => toggle('kb_ids',k.id)} />{k.name}</label>)}
            {!knowledgeBases.length && <p className="text-sm text-muted-foreground">暂无可关联的知识库</p>}
            {missingKbs.map(id => <label key={id} className="flex items-center gap-2 text-sm text-destructive"><Checkbox checked onCheckedChange={() => toggle('kb_ids',id)} />已失效或无权限的知识库（移除关联）</label>)}
          </div>
          <Button variant="link" className="px-0" onClick={() => onManage('knowledge')}>管理知识库</Button>
        </fieldset>
      </div>
      <p className="text-sm text-muted-foreground">保存后，此空间内所有会话的后续提问将使用更新后的来源。历史回答保持不变。未关联来源的空间会标记为“待配置”。</p>
      {(missingKbs.length > 0 || missingSources.length > 0) && <Alert variant="destructive"><AlertDescription>请移除或替换失效关联后保存。</AlertDescription></Alert>}
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription>{form.id && <Button variant="link" disabled={busy} onClick={async () => { setBusy(true); try { const spaces = await apiRequest<Workspace[]>('/workspaces'); const fresh = spaces.find(w => w.id === form.id); if (fresh) {onSaved(fresh); edit(fresh);} } catch (e: any) {setError(e.message);} finally {setBusy(false);} }}>重新载入空间配置（放弃本次编辑）</Button>}</Alert>}
      <div className="flex justify-end gap-2"><Button variant="outline" disabled={busy} onClick={() => {setForm(null);setError('');}}>取消</Button><Button disabled={busy || !form.name.trim() || missingKbs.length > 0 || missingSources.length > 0} onClick={() => {void save();}}>{busy ? '保存中…' : '保存'}</Button></div>
    </CardContent></Card> : <div className="grid gap-4 sm:grid-cols-2">{workspaces.map(w => <Card key={w.id}><CardHeader><CardTitle role="heading" aria-level={2} className="text-base">{w.name}</CardTitle></CardHeader><CardContent className="space-y-4">
      <p className="text-sm text-muted-foreground">业务数据源 {w.source_ids.length} 个 · 知识库 {w.kb_ids.length} 个</p>
      <p className={w.status === 'invalid' ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}>{w.status === 'invalid' ? '存在失效或无权限关联，请检查配置' : w.status === 'empty' ? '待配置' : '可用'}{w.name.includes(' · 历史范围 ') && ' · 已保留历史会话范围'}</p>
      <div className="flex gap-2"><Button variant="outline" onClick={() => edit(w)} aria-label={`编辑 ${w.name}`}>编辑</Button><Button onClick={() => onStart(w.id)} aria-label={`在 ${w.name} 新建对话`}>新建对话</Button></div>
    </CardContent></Card>)}</div>}
  </section>;
}
