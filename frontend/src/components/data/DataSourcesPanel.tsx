import React, { useEffect, useRef, useState } from 'react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Table, TableBody, TableRow, TableCell, TableHeader, TableHead } from '../ui/table';
import { Alert, AlertDescription } from '../ui/alert';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '../ui/alert-dialog';
import { toast } from 'sonner';
import { apiRequest } from '../../services/api';

export interface DataSource {
  id: string; name: string; kind: string; description: string; schema_name: string; allowed_views: string[];
}
interface Metric { id: string; name: string; description: string; unit: string; }
interface Column { table_name: string; column_name: string; data_type: string; }

export const DataSourcesPanel: React.FC = () => {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const [pendingDelete, setPendingDelete] = useState<{label: string; action: () => Promise<void>} | null>(null);
  const [failed, setFailed] = useState(false);
  const reportError = (error: unknown) => { setFailed(true); setNotice(error instanceof Error ? error.message : '操作失败'); };
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [sourceId, setSourceId] = useState('');
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [metricName, setMetricName] = useState('');
  const [definition, setDefinition] = useState('');
  const [sql, setSql] = useState('');
  const [unit, setUnit] = useState('');
  const [columns, setColumns] = useState<Column[]>([]);
  const [querySource, setQuerySource] = useState('');
  const [query, setQuery] = useState('SELECT * FROM dataset LIMIT 10');
  const [result, setResult] = useState<{rows: Record<string, unknown>[]; truncated: boolean} | null>(null);
  const load = () => apiRequest<DataSource[]>('/data-sources').then(setSources);
  useEffect(() => { load().catch(reportError); }, []);
  useEffect(() => {
    setMetrics([]);
    if (sourceId) apiRequest<Metric[]>(`/data-sources/${sourceId}/metrics`).then(setMetrics).catch(reportError);
  }, [sourceId]);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setNotice(''); setFailed(false);
    try { await fn(); return true; } catch (e) { reportError(e); return false; } finally { setBusy(false); }
  };
  const resultColumns = Array.from(new Set(result?.rows.flatMap(row => Object.keys(row)) || []));
  const field = 'w-full rounded-lg border border-input bg-transparent p-2 text-sm';
  return <section className="rounded-2xl border border-border bg-card text-card-foreground p-6 space-y-4">
    <h2 className="font-semibold">业务数据 · CSV / Excel 导入</h2>
    <p className="text-sm text-muted-foreground">文件首行为列名。支持 UTF-8 CSV 和 .xlsx；每次导入保存独立快照，聊天时可勾选使用。金额与统计直接查询文件中的真实数据。</p>
    {notice && <Alert variant={failed ? "destructive" : "default"} role={failed ? "alert" : "status"}><AlertDescription className="whitespace-pre-wrap">{notice}</AlertDescription></Alert>}
    <form className="grid md:grid-cols-2 gap-3" onSubmit={e => { e.preventDefault(); run(async () => {
      if (!file) throw new Error('请选择 CSV 或 Excel 文件');
      const form = new FormData(); form.append('name', name); form.append('file', file);
      if (sheet.trim()) form.append('sheet', sheet.trim());
      const imported = await apiRequest<DataSource & {row_count: number; columns: Column[]; sheet: string | null; sheets: string[]}>('/data-sources/import', {method:'POST', body:form});
      setColumns(imported.columns); setName(''); setFile(null); setSheet('');
      if (fileInput.current) fileInput.current.value = '';
      await load(); setQuerySource(imported.id); setResult(null);
      setNotice(`已导入 ${imported.row_count} 行、${imported.columns.length} 列。${imported.sheet ? `本次工作表：${imported.sheet}。` : ''}${imported.sheets.length > 1 ? '其他工作表请分别导入。' : ''}返回聊天后勾选该数据集即可提问。`);
    }); }}>
      <label className="text-sm">数据集名称<Input required maxLength={100} value={name} onChange={e => setName(e.target.value)} className={field}/></label>
      <label className="text-sm">业务文件<Input ref={fileInput} required type="file" accept=".csv,.xlsx" onChange={e => { const selected = e.target.files?.[0] || null; setFile(selected); if (selected && !name) setName(selected.name.replace(/\.[^.]+$/, '')); }} className={field}/></label>
      <label className="text-sm">Excel 工作表（留空使用第一张）<Input value={sheet} onChange={e => setSheet(e.target.value)} className={field}/></label>
      <p className="text-xs text-muted-foreground self-center">最多 50MB、10 万行、200 列。公式需先粘贴为值；旧版 .xls 请另存为 .xlsx。</p>
      <Button size="sm" disabled={busy}>{busy ? '处理中…' : '导入业务数据'}</Button>
    </form>
    <div className="space-y-2">{sources.map(s => <div key={s.id} className="flex flex-wrap items-center justify-between border-t border-border pt-3 gap-2 text-sm">
      <div><p>{s.name} · {s.allowed_views.join(', ')}</p><p className="text-xs text-muted-foreground">{s.description}</p></div>
      <div className="flex gap-3">
        <Button variant="outline" size="sm" disabled={busy} onClick={() => run(async () => { const r = await apiRequest<{columns: Column[]}>(`/data-sources/${s.id}/test`, {method:'POST'}); setColumns(r.columns); setQuerySource(s.id); setResult(null); setNotice('已读取数据集字段，可在下方预览或查询'); })} className="text-primary">查看数据</Button>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => setSourceId(s.id)} className="text-primary">指标口径</Button>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => setPendingDelete({label: `数据集“${s.name}”`, action: async () => { await apiRequest(`/data-sources/${s.id}`, {method:'DELETE'}); if(sourceId === s.id) setSourceId(''); if(querySource === s.id) {setQuerySource(''); setColumns([]); setResult(null);} await load(); toast.success('数据集已移除'); }})} className="text-red-600 dark:text-red-400">移除数据集</Button>
      </div>
    </div>)}</div>
    {columns.length > 0 && <div className="overflow-auto max-h-56"><Table className="text-xs w-full text-left"><TableHeader><TableRow><TableHead>数据集</TableHead><TableHead>字段</TableHead><TableHead>类型</TableHead></TableRow></TableHeader><TableBody>{columns.map(c => <TableRow key={`${c.table_name}.${c.column_name}`} className="border-t border-border"><TableCell className="p-2">{c.table_name}</TableCell><TableCell>{c.column_name}</TableCell><TableCell>{c.data_type}</TableCell></TableRow>)}</TableBody></Table></div>}
    {querySource && <form className="space-y-2 border-t pt-4" onSubmit={e => {e.preventDefault(); run(async () => {
      setResult(await apiRequest(`/data-sources/${querySource}/query`, {method:'POST', body:JSON.stringify({sql:query})}));
    });}}>
      <label className="block text-sm">{sources.find(s => s.id === querySource)?.name} · 只读查询<Textarea required value={query} onChange={e => setQuery(e.target.value)} rows={3} className={field}/></label>
      <Button variant="outline" size="sm" disabled={busy} className="text-sm text-primary">执行查询</Button>
      {result && <div><p className="text-xs text-muted-foreground">返回 {result.rows.length} 行{result.truncated ? '（已截断）' : ''}</p><div className="max-h-72 overflow-auto"><Table aria-label="业务查询结果"><TableHeader><TableRow>{resultColumns.map(key => <TableHead key={key}>{key}</TableHead>)}</TableRow></TableHeader><TableBody>{result.rows.map((row, index) => <TableRow key={index}>{resultColumns.map(key => <TableCell key={key}>{row[key] == null ? '—' : typeof row[key] === 'object' ? JSON.stringify(row[key]) : String(row[key])}</TableCell>)}</TableRow>)}</TableBody></Table>{!result.rows.length && <p className="p-3 text-sm text-muted-foreground">没有符合条件的数据。</p>}</div></div>}
    </form>}
    {sourceId && <form className="space-y-3 border-t pt-4" onSubmit={e => { e.preventDefault(); run(async () => {
      await apiRequest(`/data-sources/${sourceId}/metrics`, {method:'POST', body:JSON.stringify({name:metricName, description:definition, sql_template:sql, unit})});
      setMetrics(await apiRequest<Metric[]>(`/data-sources/${sourceId}/metrics`)); setNotice('业务指标已保存'); toast.success('业务指标已保存');
    }); }}>
      <h3 className="font-medium">{sources.find(s => s.id === sourceId)?.name} · 指标定义</h3>
      <p className="text-xs text-muted-foreground">SQL 使用 :start_date 和 :end_date 表达日期范围（开始包含，结束不包含）。说明应包含过滤规则、币种和去重方式。字段含中文或空格时使用双引号。</p>
      {metrics.map(m => <p key={m.id} className="text-sm">{m.name}（{m.unit}）：{m.description} <Button variant="outline" size="sm" type="button" className="text-red-600 dark:text-red-400" onClick={() => setPendingDelete({label: `指标“${m.name}”`, action: async () => { await apiRequest(`/data-sources/${sourceId}/metrics/${m.id}`, {method:'DELETE'}); setMetrics(items => items.filter(item => item.id !== m.id)); toast.success('指标已移除'); }})}>移除指标</Button></p>)}
      <label className="block text-sm">指标名称<Input required value={metricName} onChange={e => setMetricName(e.target.value)} className={field}/></label>
      <label className="block text-sm">业务口径<Textarea required value={definition} onChange={e => setDefinition(e.target.value)} className={field}/></label>
      <label className="block text-sm">SQL 模板<Textarea required rows={4} value={sql} onChange={e => setSql(e.target.value)} placeholder={'SELECT SUM("金额") AS total FROM dataset WHERE "日期" >= :start_date AND "日期" < :end_date'} className={field}/></label>
      <label className="block text-sm">单位<Input value={unit} onChange={e => setUnit(e.target.value)} className={field}/></label>
      <Button size="sm" disabled={busy}>保存指标</Button>
    </form>}
    <AlertDialog open={!!pendingDelete} onOpenChange={open => { if (!open && !busy) setPendingDelete(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>确认移除？</AlertDialogTitle><AlertDialogDescription>将移除{pendingDelete?.label}，此操作无法撤销。</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel disabled={busy}>取消</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={async e => { e.preventDefault(); if (pendingDelete && await run(pendingDelete.action)) setPendingDelete(null); }}>{busy ? '正在移除…' : '确认移除'}</AlertDialogAction></AlertDialogFooter>
        {failed && notice && <Alert variant="destructive"><AlertDescription>{notice}</AlertDescription></Alert>}
      </AlertDialogContent>
    </AlertDialog>
  </section>;
};
